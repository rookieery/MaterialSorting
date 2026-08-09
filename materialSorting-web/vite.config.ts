import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

// dev: base 为 /，build: base 为 /static/（FastAPI 由 /static 路径 serve 构建产物）。
// /export 与 /ws 走 Vite dev proxy → 后端 :8000，因此 dev/prod 前端代码用相对路径即可。
export default defineConfig(({ command }) => ({
  base: command === 'build' ? '/static/' : '/',
  plugins: [react()],
  build: {
    outDir: 'static',
    emptyOutDir: true,
  },
  server: {
    port: 5173,
    strictPort: true,
    proxy: {
      '/export': {
        target: 'http://127.0.0.1:8000',
        changeOrigin: true,
      },
      '/ws': {
        target: 'http://127.0.0.1:8000',
        ws: true,
        changeOrigin: true,
      },
    },
  },
}));
