import { defineConfig } from 'vite';
export default defineConfig({
  // Open pages may still request older lazy chunks after an in-place update.
  build:{target:['es2020','safari15'],emptyOutDir:false},
  server:{proxy:{'/api':{target:'http://127.0.0.1:8765',ws:true}}},
});
