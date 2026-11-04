/**
 * Pixel sprites.
 *
 * A sprite is a list of 8 rows of 8 characters; `1` paints a cell, `0` leaves
 * it empty. Everything renders as integer-aligned SVG rects with
 * `shapeRendering="crispEdges"`, so it stays sharp at any DPR without a sprite
 * sheet.
 */
export type PixelSprite =
  | 'spark'
  | 'folder'
  | 'terminal'
  | 'check'
  | 'cross'
  | 'diamond'
  | 'pause'
  | 'tick'
  | 'checker'
  | 'dot';

export const PIXEL_SPRITES: Record<PixelSprite, string[]> = {
  spark: [
    '00011000',
    '00011000',
    '00111100',
    '11111111',
    '11111111',
    '00111100',
    '00011000',
    '00011000',
  ],
  folder: [
    '00000000',
    '01111000',
    '11111100',
    '11111110',
    '11111110',
    '11111110',
    '11111110',
    '00000000',
  ],
  terminal: [
    '11111110',
    '10000010',
    '10110110',
    '10000010',
    '10110110',
    '10000010',
    '11111110',
    '00000000',
  ],
  check: [
    '00000000',
    '00000011',
    '00000110',
    '00001100',
    '11011000',
    '01110000',
    '00100000',
    '00000000',
  ],
  cross: [
    '00000000',
    '01000010',
    '00100100',
    '00011000',
    '00011000',
    '00100100',
    '01000010',
    '00000000',
  ],
  diamond: [
    '00011000',
    '00111100',
    '01111110',
    '11111111',
    '11111111',
    '01111110',
    '00111100',
    '00011000',
  ],
  pause: [
    '00000000',
    '00110011',
    '00110011',
    '00110011',
    '00110011',
    '00110011',
    '00110011',
    '00000000',
  ],
  tick: [
    '00000000',
    '00000011',
    '00000011',
    '00000011',
    '00000011',
    '11000011',
    '11000011',
    '00000000',
  ],
  checker: [
    '00000000',
    '01100110',
    '01100110',
    '00000000',
    '00000000',
    '01100110',
    '01100110',
    '00000000',
  ],
  dot: [
    '00000000',
    '00000000',
    '00000000',
    '00011000',
    '00011000',
    '00000000',
    '00000000',
    '00000000',
  ],
};

export function blockSprite(x: number, y: number, size = 2): string[] {
  return Array.from({ length: 8 }, (_, row) =>
    Array.from({ length: 8 }, (_, col) =>
      col >= x && col < x + size && row >= y && row < y + size ? '1' : '0',
    ).join(''),
  );
}

/** Build the four corner-walk frames used by the live loader. */
export const LOADER_SPRITES: string[][] = [
  blockSprite(0, 0),
  blockSprite(6, 0),
  blockSprite(6, 6),
  blockSprite(0, 6),
];

export function rowsToShapes(rows: string[], cell = 1) {
  const shapes: { x: number; y: number; w: number }[] = [];
  rows.forEach((row, y) => {
    let x = 0;
    while (x < row.length) {
      if (row[x] !== '1') {
        x += 1;
        continue;
      }
      // Merge horizontal runs into one rect to keep the DOM small.
      let run = 1;
      while (row[x + run] === '1') run += 1;
      shapes.push({ x: x * cell, y: y * cell, w: run * cell });
      x += run;
    }
  });
  return shapes;
}

export function spriteCells(sprite: PixelSprite, cell = 1) {
  return rowsToShapes(PIXEL_SPRITES[sprite], cell);
}
