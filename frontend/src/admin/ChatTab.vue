<template>
  <div>
    <div class="section-head">
      <div>
        <h2 class="section-title">AI 对话测试</h2>
        <p class="section-desc">与客户端相同的 SSE 问答逻辑；管理端的对话单独留存在「对话」记录中</p>
      </div>
      <div class="upload-actions" style="margin-top: 0;">
        <button class="btn btn-sm" type="button" @click="panel && panel.openDrawer()">历史对话</button>
        <button class="btn btn-sm" type="button" @click="panel && panel.startNewChat()">新对话</button>
      </div>
    </div>

    <div class="admin-chat">
      <ChatPanel ref="panel" mode="admin" :token="token" scope="admin" />
    </div>
  </div>
</template>

<script setup>
import { ref } from 'vue'
import ChatPanel from '../components/ChatPanel.vue'

defineProps({
  token: { type: String, default: '' }
})

const panel = ref(null)
</script>

<style scoped>
.admin-chat {
  height: calc(100dvh - 205px);
  min-height: 360px;
}
</style>
