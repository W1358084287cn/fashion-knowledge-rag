<template>
  <Transition name="toast-fade">
    <div v-if="message" class="toast" :class="{ error: type === 'error' }">{{ message }}</div>
  </Transition>
</template>

<script setup>
defineProps({
  message: { type: String, default: '' },
  type: { type: String, default: 'info' }
})
</script>

<style scoped>
.toast-fade-enter-active,
.toast-fade-leave-active {
  transition: opacity 0.2s ease;
}

.toast-fade-enter-from,
.toast-fade-leave-to {
  opacity: 0;
}
</style>
