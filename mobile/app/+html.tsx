import { ScrollViewStyleReset } from 'expo-router/html';
import { Asset } from 'expo-asset';
import type { PropsWithChildren } from 'react';

import { CLERK_PUBLISHABLE_KEY } from '@/constants/config';
import { FONTS } from '@/constants/fonts';

// Page background before the app paints (no white flash in dark mode), a clear
// keyboard focus ring, and reduced motion when the device asks for it.
const CSS = `
html, body { background-color: #FFF9E3; }
:focus-visible { outline: 2px solid #BD512E; outline-offset: 2px; }
@media (prefers-color-scheme: dark) {
  html, body { background-color: #0C0C0D; }
  :focus-visible { outline-color: #D4AF37; }
}
@media (prefers-reduced-motion: reduce) {
  *, *::before, *::after { animation-duration: 0.01ms !important; transition-duration: 0.01ms !important; scroll-behavior: auto !important; }
}
`;

// The app's fonts, declared up front so pre-rendered text paints in them
// (the same files and family names expo-font registers once the app runs).
const FONT_FACES = Object.entries(FONTS)
  .map(([family, mod]) => `@font-face{font-family:${family};src:url(${Asset.fromModule(mod).uri});font-display:swap}`)
  .join('');

// Clerk's sign-in server (encoded in the publishable key): connect early so sign-in is ready sooner.
const CLERK_ORIGIN = (() => {
  try {
    return `https://${atob(CLERK_PUBLISHABLE_KEY.split('_')[2]).replace(/\$$/, '')}`;
  } catch {
    return null;
  }
})();

/** The web build's HTML shell (static rendering): title, description and theme color. */
export default function Root({ children }: PropsWithChildren) {
  return (
    <html lang="en">
      <head>
        <meta charSet="utf-8" />
        <meta httpEquiv="X-UA-Compatible" content="IE=edge" />
        <meta name="viewport" content="width=device-width, initial-scale=1, shrink-to-fit=no" />
        <title>DFSRiches</title>
        {CLERK_ORIGIN ? <link rel="preconnect" href={CLERK_ORIGIN} crossOrigin="anonymous" /> : null}
        <meta name="description" content="NFL DraftKings projections, ownership, leverage and lineup building." />
        <meta name="theme-color" content="#FFF9E3" media="(prefers-color-scheme: light)" />
        <meta name="theme-color" content="#0C0C0D" media="(prefers-color-scheme: dark)" />
        <ScrollViewStyleReset />
        <style dangerouslySetInnerHTML={{ __html: CSS + FONT_FACES }} />
      </head>
      <body>{children}</body>
    </html>
  );
}
