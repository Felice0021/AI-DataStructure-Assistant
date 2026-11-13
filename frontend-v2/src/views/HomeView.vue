<script setup lang="ts">
import AuthPanel from '@/components/AuthPanel.vue'
import ChatWorkspace from './ChatWorkspace.vue'
import { useAuthStore } from '@/stores/auth'
const auth = useAuthStore()
</script>
<template><ChatWorkspace v-if="auth.isAuthenticated" :key="auth.user!.id" /><AuthPanel v-else /></template>
