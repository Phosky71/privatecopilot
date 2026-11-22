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

export function parseContent(content: string): ContentPart[] {
  const parts: ContentPart[] = [];
  let lastIndex = 0;
  let match: RegExpExecArray | null;

  // Reset regex state for repeated calls.
  EDIT_REGEX.lastIndex = 0;

  while ((match = EDIT_REGEX.exec(content)) !== null) {
    if (match.index > lastIndex) {
      parts.push({ type: 'text', content: content.slice(lastIndex, match.index) });
    }
    parts.push({
      type: 'edit',
      file: match[1],
      original: match[2].replace(/^\n/, ''),
      replacement: match[3].replace(/^\n/, ''),
    });
    lastIndex = EDIT_REGEX.lastIndex;
  }

  if (lastIndex < content.length) {
    parts.push({ type: 'text', content: content.slice(lastIndex) });
  }

  return parts;
}
