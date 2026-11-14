<script setup lang="ts">
import { computed } from 'vue'
import type { VerifiedTree } from '@/utils/verifiedTree'
import TreeDiagram from './TreeDiagram.vue'
const props = defineProps<{ tree: VerifiedTree }>()
const binary = computed(() => ['AVL', 'BST'].includes(props.tree.family))
const stageLabel = { before: '旋转前', intermediate: '第一次旋转后', after: '旋转后' }
const needsFinal = computed(() => {
  const frames = props.tree.rotations[props.tree.rotations.length - 1]?.frames
  const last = frames?.[frames.length - 1]?.graph
  return !last || JSON.stringify(last) !== JSON.stringify(props.tree.final)
})
</script>
<template>
  <section class="verified-tree" aria-label="服务端已校验树形图">
    <p class="tree-origin">{{ tree.family }} · 服务端参考算法计算并校验</p>
    <section v-for="(rotation, index) in tree.rotations" :key="index" class="tree-rotation">
      <h4>{{ rotation.kind }} 旋转{{ tree.rotations.length > 1 ? ` · 第 ${index + 1} 次` : '' }}<span>局部子树</span></h4>
      <div class="tree-sequence">
        <TreeDiagram v-for="frame in rotation.frames" :key="frame.stage" :graph="frame.graph" :binary="true" :label="`${rotation.kind} · ${stageLabel[frame.stage]}`" />
      </div>
    </section>
    <TreeDiagram v-if="needsFinal" :graph="tree.final" :binary="binary" label="最终完整树" />
    <p v-else class="tree-final-note">最后一幅旋转后结构即最终完整树。</p>
    <p v-if="tree.family === 'B+'" class="tree-final-note">矩形内为有序关键字；内部关键字用于导航，记录键位于叶结点。</p>
  </section>
</template>
<style scoped>
.verified-tree { min-width: 0; max-width: 100%; margin: 18px 0; }
.tree-origin, .tree-final-note { color: #737373; font-size: 12px; line-height: 1.7; }
.tree-rotation { margin-bottom: 16px; min-width: 0; }
h4 { margin: 12px 0; color: #262626; font-size: 14px; font-weight: 600; }
h4 span { margin-left: 10px; color: #737373; font-size: 12px; font-weight: 400; }
.tree-sequence { display: grid; grid-template-columns: repeat(auto-fit, minmax(min(100%, 220px), 1fr)); gap: 14px; min-width: 0; }
@media (max-width: 600px) { .tree-sequence { grid-template-columns: minmax(0, 1fr); } }
</style>
