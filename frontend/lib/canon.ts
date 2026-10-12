/** Lines from the Holmes stories (Arthur Conan Doyle, public domain), quoted as published. */

export type CanonQuote = { text: string; source: string };

export const CANON = {
  observe: {
    text: "You see, but you do not observe.",
    source: "A Scandal in Bohemia, 1891",
  },
  data: {
    text: "It is a capital mistake to theorize before one has data.",
    source: "A Scandal in Bohemia, 1891",
  },
  clay: {
    text: "Data! data! data! I can't make bricks without clay.",
    source: "The Adventure of the Copper Beeches, 1892",
  },
  impossible: {
    text: "When you have eliminated the impossible, whatever remains, however improbable, must be the truth.",
    source: "The Sign of the Four, 1890",
  },
  afoot: {
    text: "Come, Watson, come! The game is afoot.",
    source: "The Adventure of the Abbey Grange, 1904",
  },
  obvious: {
    text: "There is nothing more deceptive than an obvious fact.",
    source: "The Boscombe Valley Mystery, 1891",
  },
  littleThings: {
    text: "It has long been an axiom of mine that the little things are infinitely the most important.",
    source: "A Case of Identity, 1891",
  },
  business: {
    text: "It is my business to know what other people don't know.",
    source: "The Adventure of the Blue Carbuncle, 1892",
  },
  education: {
    text: "Education never ends, Watson. It is a series of lessons with the greatest for the last.",
    source: "His Last Bow: The Red Circle, 1911",
  },
} satisfies Record<string, CanonQuote>;

export const ALL_QUOTES: CanonQuote[] = Object.values(CANON);

export function randomQuote(): CanonQuote {
  return ALL_QUOTES[Math.floor(Math.random() * ALL_QUOTES.length)];
}
