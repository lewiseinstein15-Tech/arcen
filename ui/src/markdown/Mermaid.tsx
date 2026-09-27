// ARCEN — Mermaid lazy-load (FRONTEND-SPEC Part 5).
// The mermaid chunk downloads only when a ```mermaid fence appears.
// Render failure shows the raw fence with a warn border — never a blank block.

import { useEffect, useState } from 'react';

let mermaidPromise: Promise<typeof import('mermaid').default> | null = null;

export function getMermaid() {
  mermaidPromise ??= import('mermaid').then((m) => {
    m.default.initialize({
      startOnLoad: false,
      theme: 'dark',
      fontFamily: 'JetBrains Mono, monospace',
      securityLevel: 'strict',
    });
    return m.default;
  });
  return mermaidPromise;
}

function hash(code: string): string {
  let h = 0;
  for (let i = 0; i < code.length; i++) {
    h = (h * 31 + code.charCodeAt(i)) | 0;
  }
  return `m-${Math.abs(h).toString(36)}`;
}

export function MermaidDiagram({ code }: { code: string }) {
  const [svg, setSvg] = useState<string | null>(null);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    let cancelled = false;
    getMermaid()
      .then(async (mermaid) => {
        const { svg: rendered } = await mermaid.render(hash(code), code);
        if (!cancelled) setSvg(rendered);
      })
      .catch(() => {
        if (!cancelled) setFailed(true);
      });
    return () => {
      cancelled = true;
    };
  }, [code]);

  if (failed) {
    return (
      <pre className="mermaid-fallback" style={{ border: '1px solid var(--warn)' }}>
        {code}
      </pre>
    );
  }
  if (svg === null) {
    return <pre className="mermaid-fallback">rendering diagram…</pre>;
  }
  return <div className="mermaid" data-testid="mermaid-svg" dangerouslySetInnerHTML={{ __html: svg }} />;
}
