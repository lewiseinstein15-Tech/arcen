// ARCEN — code block + copy button (FRONTEND-SPEC Part 5).
// Shiki highlights asynchronously here (jetbrains-dark) — react-markdown's
// pipeline stays synchronous. Copy uses navigator.clipboard.writeText with
// the RAW source, never the highlighted HTML. Label copy → copied (1.5s).

import { lazy, Suspense, useEffect, useRef, useState } from 'react';

const MermaidDiagram = lazy(() =>
  import('./Mermaid').then((m) => ({ default: m.MermaidDiagram })),
);

const HIGHLIGHTED_CLASS = 'arcen-shiki';

export function CopyButton({ text }: { text: string }) {
  const [copied, setCopied] = useState(false);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(
    () => () => {
      if (timer.current) clearTimeout(timer.current);
    },
    [],
  );

  const copy = () => {
    void navigator.clipboard.writeText(text).then(
      () => {
        setCopied(true);
        if (timer.current) clearTimeout(timer.current);
        timer.current = setTimeout(() => setCopied(false), 1500);
      },
      () => setCopied(false),
    );
  };

  return (
    <button
      className="copy-btn meta"
      onClick={copy}
      aria-label={copied ? 'copied' : 'copy'}
      data-testid="copy-btn"
    >
      {copied ? 'copied' : 'copy'}
    </button>
  );
}

/** Async Shiki highlighting: jetbrains-dark, lazy grammars. */
export function useShiki(code: string, lang: string): string | null {
  const [html, setHtml] = useState<string | null>(null);
  useEffect(() => {
    let cancelled = false;
    void (async () => {
      try {
        const shiki = await import('shiki');
        const known = Object.prototype.hasOwnProperty.call(shiki.bundledLanguages, lang);
        const out = await shiki.codeToHtml(code, {
          lang: known ? lang : 'text',
          theme: 'jetbrains-dark',
        });
        if (!cancelled) setHtml(out);
      } catch {
        if (!cancelled) setHtml(null); // fall back to plain
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [code, lang]);
  return html;
}

interface CodeProps {
  className?: string;
  children?: React.ReactNode;
  rawSource?: string;
}

export function Code({ className, children, rawSource }: CodeProps) {
  const source = rawSource ?? String(children ?? '');
  const lang = /language-([\w-]+)/.exec(className ?? '')?.[1] ?? 'text';
  const isMermaid = lang === 'mermaid';
  const html = useShiki(source, lang);

  if (isMermaid) {
    return (
      <Suspense fallback={<pre className="mermaid-fallback">rendering diagram…</pre>}>
        <MermaidDiagram code={source} />
      </Suspense>
    );
  }

  return (
    <div className="code-block">
      <div className="code-head">
        <CopyButton text={source} />
      </div>
      {html !== null ? (
        <div
          className={HIGHLIGHTED_CLASS}
          data-testid="shiki-block"
          dangerouslySetInnerHTML={{ __html: html }}
        />
      ) : (
        <pre className={className}>
          <code>{children}</code>
        </pre>
      )}
    </div>
  );
}
