import { defineConfig } from 'vitest/config';
import react from '@vitejs/plugin-react';

// 独立于 vite.config.ts（避免 build/base/proxy 等生产配置污染测试）。
// vitest 自动读 vitest.config.ts 优先于 vite.config.ts。
export default defineConfig({
  plugins: [react()],
  test: {
    environment: 'jsdom',
    globals: true,
    include: ['src/**/*.{test,spec}.{ts,tsx}'],
  },
});
