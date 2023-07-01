import { createApp } from 'vue'
import './style.css'
import App from './App.vue'

createApp(App).mount('#app')

import { call, connect } from "./rpc.ts";

window.rpc = {
    call,
    connect,
}