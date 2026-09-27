// ARCEN — the AnswerBlock markdown pipeline (FRONTEND-SPEC Part 5).
// gfm · math (KaTeX) · shiki (jetbrains-dark, async in Code) · mermaid (lazy)
// · copy buttons. The remark/rehype chain itself stays synchronous.

import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import remarkMath from 'remark-math';
import rehypeKatex from 'rehype-katex';
import { Code } from './Code';
import 'katex/dist/katex.min.css';

export function Markdown({ children }: { children: string }) {
  return (
    <ReactMarkdown
      remarkPlugins={[remarkGfm, remarkMath]}
      rehypePlugins={[[rehypeKatex, { throwOnError: false, output: 'html' }]]}
      components={{
        code: ({ className, children, node }) => {
          const raw =
            (node as { text?: string } | undefined)?.text ?? extractText(children);
          return <Code className={className} rawSource={raw}>{children}</Code>;
        },
        pre: ({ children }) => <>{children}</>,
        img: ({ src, alt }) => (
          // lightbox behavior arrives with the image pass; v0.1 keeps images
          // contained and never upscaled (Part 5)
          <img src={typeof src === 'string' ? src : ''} alt={alt ?? ''} className="prose-img" />
        ),
      }}
    >
      {children}
    </ReactMarkdown>
  );
}

// pull the raw text out of shiki's highlighted children for copy buttons
function extractText(node: React.ReactNode): string {
  if (node == null || typeof node === 'boolean') return '';
  if (typeof node === 'string' || typeof node === 'number') return String(node);
  if (Array.isArray(node)) return node.map(extractText).join('');
  if (typeof node === 'object' && 'props' in node) {
    return extractText((node.props as { children?: React.ReactNode }).children);
  }
  return '';
}
