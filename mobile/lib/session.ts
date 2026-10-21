/** Where to go after signing in: the page the user was on, if it's one of ours ("/cash"), else Home. */
export function safeNext(next: string | string[] | undefined): '/' | (string & {}) {
  const n = Array.isArray(next) ? next[0] : next;
  return n && n.startsWith('/') && !n.startsWith('//') && !n.startsWith('/sign-') ? n : '/';
}
