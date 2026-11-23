export interface TextPart {
  type: 'text';
  content: string;
}

export interface EditPart {
  type: 'edit';
  file: string;
  original: string;
  replacement: string;
}

export type ContentPart = TextPart | EditPart;

const EDIT_REGEX = /<edit\s+file="([^"]+)">\s*<original>([\s\S]*?)<\/original>\s*<replacement>([\s\S]*?)<\/replacement>\s*<\/edit>/g;

function findCodeBlockRanges(content: string): Array<[number, number]> {
  const ranges: Array<[number, number]> = [];
  const fenceRegex = /(^|\n)(```|~~~)[^\n]*\n[\s\S]*?\n\2/g;
  let m: RegExpExecArray | null;
  while ((m = fenceRegex.exec(content)) !== null) {
    ranges.push([m.index, fenceRegex.lastIndex]);
  }
  return ranges;
}

function isInsideCodeBlock(index: number, ranges: Array<[number, number]>): boolean {
  return ranges.some(([start, end]) => index >= start && index < end);
}

function isTemplatePlaceholder(file: string, original: string): boolean {
  return file === 'path/to/file.ext' && original.trim() === 'exact old code to replace';
}

export function parseContent(content: string): ContentPart[] {
  const parts: ContentPart[] = [];
  let lastIndex = 0;
  let match: RegExpExecArray | null;

  const codeRanges = findCodeBlockRanges(content);

  EDIT_REGEX.lastIndex = 0;

  while ((match = EDIT_REGEX.exec(content)) !== null) {
    if (isInsideCodeBlock(match.index, codeRanges)) {
      continue;
    }
    const file = match[1];
    const original = match[2].replace(/^\n/, '');
    const replacement = match[3].replace(/^\n/, '');
    if (isTemplatePlaceholder(file, original)) {
      continue;
    }

    if (match.index > lastIndex) {
      parts.push({ type: 'text', content: content.slice(lastIndex, match.index) });
    }
    parts.push({
      type: 'edit',
      file,
      original,
      replacement,
    });
    lastIndex = EDIT_REGEX.lastIndex;
  }

  if (lastIndex < content.length) {
    parts.push({ type: 'text', content: content.slice(lastIndex) });
  }

  return parts;
}
