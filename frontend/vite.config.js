import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'
import vueJsx from '@vitejs/plugin-vue-jsx'
import { resolve } from 'path'
import AutoImport from 'unplugin-auto-import/vite'
import Components from 'unplugin-vue-components/vite'
import { ElementPlusResolver } from 'unplugin-vue-components/resolvers'
import compression from 'vite-plugin-compression'

import tailwindcss from 'tailwindcss'
import autoprefixer from 'autoprefixer'

// https://vitejs.dev/config/
export default defineConfig(({ mode }) => {
  const isProduction = mode === 'production'
  
  return {
    plugins: [
      vue(),
      vueJsx(),
      AutoImport({
        resolvers: [ElementPlusResolver()],
        imports: [
          'vue',
          'vue-router',
          'pinia',
          '@vueuse/core',
          {
            'vue-toastification': ['useToast']
          }
        ],
        dts: true
      }),
      Components({
        resolvers: [ElementPlusResolver()],
        dts: true
      }),
      
      compression({
        algorithm: 'gzip',
        ext: '.gz',
        threshold: 10240
      }),
      compression({
        algorithm: 'brotliCompress',
        ext: '.br',
        threshold: 10240
      }),
      
      
    ].filter(Boolean),
    
    resolve: {
      alias: {
        '@': resolve(__dirname, 'src'),
        '~': resolve(__dirname, 'src'),
        '@components': resolve(__dirname, 'src/components'),
        '@views': resolve(__dirname, 'src/views'),
        '@stores': resolve(__dirname, 'src/stores'),
        '@utils': resolve(__dirname, 'src/utils'),
        '@assets': resolve(__dirname, 'src/assets'),
        '@services': resolve(__dirname, 'src/services'),
        '@types': resolve(__dirname, 'src/types'),
        '@composables': resolve(__dirname, 'src/composables'),
        '@constants': resolve(__dirname, 'src/constants')
      }
    },
    
    css: {
      preprocessorOptions: {
        scss: {
          additionalData: `@import "@/styles/variables.scss";`
        }
      },
      postcss: {
        plugins: [
          tailwindcss(),
          autoprefixer()
        ]
      }
    },
    
    server: {
      host: '0.0.0.0',
      port: 5173,
      open: true,
      proxy: {
        '/api': {
          target: 'http://localhost:8000',
          changeOrigin: true,
          rewrite: (path) => path.replace(/^\/api/, '/api/v1')
        },
        '/ws': {
          target: 'ws://localhost:8000',
          ws: true
        }
      },
      hmr: {
        overlay: true
      }
    },
    
    build: {
      target: 'esnext',
      outDir: 'dist',
      assetsDir: 'assets',
      sourcemap: mode === 'development',
      minify: 'terser',
      terserOptions: {
        compress: {
          drop_console: isProduction,
          drop_debugger: isProduction
        }
      },
      rollupOptions: {
        output: {
          manualChunks: {
            'vue-vendor': ['vue', 'vue-router', 'pinia'],
            'ui-vendor': ['element-plus', '@element-plus/icons-vue'],
            'utils-vendor': ['axios', 'lodash-es', 'dayjs'],
            'charts-vendor': ['echarts', 'vue-echarts']
          }
        }
      },
      chunkSizeWarningLimit: 1000
    },
    
    optimizeDeps: {
      include: [
        'vue',
        'vue-router',
        'pinia',
        'axios',
        'element-plus',
        'dayjs',
        'lodash-es',
        'echarts',
        'vue-echarts'
      ]
    },

    test: {
      environment: 'jsdom',
      globals: true,
      include: [
        'tests/unit/**/*.spec.[jt]s?(x)',
        'tests/unit/**/*.test.[jt]s?(x)'
      ],
      exclude: [
        'node_modules/**',
        'dist/**',
        'cypress/**',
        'playwright/**',
        'e2e/**',
        'tests/app.spec.js',
        'tests/**/*.e2e.[jt]s?(x)'
      ]
    },
    
    define: {
      __VUE_OPTIONS_API__: true,
      __VUE_PROD_DEVTOOLS__: false
    },
    
    envPrefix: ['VITE_', 'GAP_']
  }
})