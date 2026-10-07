import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from "@tailwindcss/vite";

/**
 * RAG/메일 API는 same-origin 상대경로로 호출한다.
 * - 개발: 아래 proxy가 FastAPI(기본 127.0.0.1:8000)로 넘긴다
 * - 배포: FastAPI가 dist/를 직접 서빙하므로 프록시 없이 그대로 동작한다 (main.py)
 * 백엔드 주소가 다르면 VITE_PROXY_TARGET 으로 바꾼다.
 * (OCR은 별도 서버(8082)라 App.tsx에서 절대 URL로 호출한다.)
 */
const API_TARGET = process.env.VITE_PROXY_TARGET ?? 'http://127.0.0.1:8000'

// https://vite.dev/config/
export default defineConfig({
  plugins: [
      react(),
      tailwindcss(),
  ],
  server: {
    proxy: {
      '/upload': API_TARGET,
      '/files': API_TARGET,
      '/file/': API_TARGET,
      '/ask': API_TARGET,
      '/search': API_TARGET,
      '/mails': API_TARGET,
    },
  },
})
