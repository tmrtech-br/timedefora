import type { GameCard } from './types';

let preview: GameCard | undefined;

export function rememberGamePreview(game: GameCard) {
  preview = game;
}

export function getGamePreview(slug: string) {
  return preview?.slug === slug ? preview : undefined;
}
