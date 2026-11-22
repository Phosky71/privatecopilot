import { test } from 'node:test';
import assert from 'node:assert/strict';
import { parseContent } from './editParser.ts';

test('returns single text part when no edit tags', () => {
  const parts = parseContent('hello world');
  assert.deepEqual(parts, [{ type: 'text', content: 'hello world' }]);
});

test('returns empty array for empty string', () => {
  const parts = parseContent('');
  assert.deepEqual(parts, []);
});

test('parses a single edit block', () => {
  const input = '<edit file="a.txt"><original>old</original><replacement>new</replacement></edit>';
  const parts = parseContent(input);
  assert.deepEqual(parts, [{ type: 'edit', file: 'a.txt', original: 'old', replacement: 'new' }]);
});

test('handles text before and after edit', () => {
  const input = 'before\n<edit file="a.txt"><original>old</original><replacement>new</replacement></edit>\nafter';
  const parts = parseContent(input);
  assert.equal(parts.length, 3);
  assert.deepEqual(parts[0], { type: 'text', content: 'before\n' });
  assert.deepEqual(parts[1], { type: 'edit', file: 'a.txt', original: 'old', replacement: 'new' });
  assert.deepEqual(parts[2], { type: 'text', content: '\nafter' });
});

test('parses multiple edit blocks', () => {
  const input =
    '<edit file="a.txt"><original>x</original><replacement>y</replacement></edit>' +
    'mid' +
    '<edit file="b.txt"><original>u</original><replacement>v</replacement></edit>';
  const parts = parseContent(input);
  assert.equal(parts.length, 3);
  assert.equal(parts.filter(p => p.type === 'edit').length, 2);
});

test('strips leading newline from original and replacement', () => {
  const input = '<edit file="a.txt"><original>\nold</original><replacement>\nnew</replacement></edit>';
  const parts = parseContent(input);
  assert.deepEqual(parts[0], { type: 'edit', file: 'a.txt', original: 'old', replacement: 'new' });
});

test('incomplete tag during streaming does not crash', () => {
  const input = 'partial <edit file="a.txt"><original>old</original><replacement>new';
  const parts = parseContent(input);
  // Should not throw; unmatched tail becomes text
  assert.ok(Array.isArray(parts));
  assert.ok(parts.some(p => p.type === 'text'));
});

test('malformed edit without closing tag is treated as text', () => {
  const input = '<edit file="a.txt"><original>old</original>';
  const parts = parseContent(input);
  assert.deepEqual(parts, [{ type: 'text', content: input }]);
});