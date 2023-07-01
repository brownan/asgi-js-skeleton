import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

// https://vitejs.dev/config/
export default defineConfig({
    plugins: [vue()],
    build: {
        outDir: "../static",
        emptyOutDir: true,
        minify: false,
        cssMinify: false,
        rollupOptions: {
            output: {
                entryFileNames: `[name].js`,
                chunkFileNames: `[name].js`,
                assetFileNames: `[name].[ext]`,
            }
        }
    },
    server: {
        proxy: {
            "/ws": {target: "http://localhost:8888", ws: true}
        }
    }
})
