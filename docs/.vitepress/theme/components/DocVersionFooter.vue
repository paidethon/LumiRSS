<template>
  <div class="lumi-build-info">
    <span>LumiRSS {{ build.version }}</span>
    <span aria-hidden="true">·</span>
    <span>Commit <code>{{ build.commit }}</code></span>
    <span aria-hidden="true">·</span>
    <span>Docs updated {{ build.date }}</span>
  </div>
</template>

<script setup>
const build = __LUMI_DOCS_BUILD__
</script>
