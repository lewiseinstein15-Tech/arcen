import react from '@vitejs/plugin-react';
import { defineConfig } from 'vitest/config';

export default defineConfig({
  plugins: [react()],
  test: {
    environment: 'jsdom',
    globals: true,
    setupFiles: ['tests/setup.ts'],
    include: ['tests/**/*.test.ts', 'tests/**/*.test.tsx'],
  },
  server: {
    port: 5173,
    proxy: {
      '/api': {
        target: 'http://localhost:3002',
        changeOrigin: true,
      },
    },
  },
  build: {
    target: 'es2022',
    rollupOptions: {
      output: {
        manualChunks: {
          mermaid: ['mermaid'],
          shiki: ['shiki', '@shikijs/rehype'],
          katex: ['katex'],
        },
      },
    },
  },
});
