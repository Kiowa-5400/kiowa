import path from 'node:path';
import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

// Code shared by the three apps lives in apps/shared and is imported as "@shared/...".
export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: { '@shared': path.resolve(__dirname, '../shared') },
    // Resolve React from this app's node_modules even when imported by shared code.
    dedupe: ['react', 'react-dom'],
  },
  server: {
    host: '0.0.0.0',
    port: 5174,
    fs: { allow: ['..'] },
  },
  preview: {
    host: '0.0.0.0',
    port: 5174,
  },
  build: {
    sourcemap: false,
  },
});
