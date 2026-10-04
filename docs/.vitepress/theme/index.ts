// LumiRSS docs theme: default VitePress theme + Lumi visual layer.
// No custom components beyond the build-info footer; Base-UI-style overlay
// mechanics stay owned by the default theme.
import { h } from 'vue'
import DefaultTheme from 'vitepress/theme'
import DocVersionFooter from './components/DocVersionFooter.vue'
import './custom.css'

export default {
  extends: DefaultTheme,
  Layout() {
    return h(DefaultTheme.Layout, null, {
      // doc pages: above the prev/next footer; home: right after features.
      'doc-footer-before': () => h(DocVersionFooter),
      'home-features-after': () => h(DocVersionFooter),
    })
  },
}
