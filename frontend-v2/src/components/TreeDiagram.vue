<script setup lang="ts">
import { computed, useId } from 'vue'
import { layoutTree, type TreeGraph } from '@/utils/verifiedTree'
const props = defineProps<{ graph: TreeGraph; binary: boolean; label: string }>()
const titleId = useId()
const layout = computed(() => layoutTree(props.graph, props.binary))
</script>

<template>
  <figure class="tree-figure">
    <figcaption>{{ label }}</figcaption>
    <div class="tree-scroll" role="region" :aria-label="`${label}，树形图可横向滚动`" tabindex="0">
      <svg class="tree-svg" role="img" :aria-labelledby="titleId" :width="layout.width" :height="layout.height" :viewBox="`0 0 ${layout.width} ${layout.height}`">
        <title :id="titleId">{{ label }}；{{ layout.nodes.length }} 个结点</title>
        <g class="tree-edges" aria-hidden="true">
          <g v-for="edge in layout.edges" :key="`${edge.from}-${edge.to}`">
            <line :x1="edge.x1" :y1="edge.y1" :x2="edge.x2" :y2="edge.y2" />
            <text v-if="edge.side" :x="(edge.x1 + edge.x2) / 2 + (edge.side === '左' ? -9 : 9)" :y="(edge.y1 + edge.y2) / 2">{{ edge.side }}</text>
          </g>
        </g>
        <g v-for="node in layout.nodes" :key="node.id" class="tree-node" :data-node="node.id" :transform="`translate(${node.x},${node.y})`">
          <circle v-if="binary" :r="node.width / 2" />
          <rect v-else :x="-node.width / 2" :y="-node.height / 2" :width="node.width" :height="node.height" rx="5" />
          <template v-for="(key, index) in node.keys" :key="index">
            <line v-if="!binary && index" class="tree-divider" :x1="-node.width / 2 + node.width * index / node.keys.length" :x2="-node.width / 2 + node.width * index / node.keys.length" :y1="-node.height / 2" :y2="node.height / 2" />
            <text :x="binary ? 0 : -node.width / 2 + node.width * (index + 0.5) / node.keys.length" y="1">{{ key }}</text>
          </template>
        </g>
      </svg>
    </div>
  </figure>
</template>

<style scoped>
.tree-figure { margin: 0; min-width: 0; max-width: 100%; }
figcaption { margin: 0 0 8px; font-size: 13px; color: #525252; font-weight: 500; }
.tree-scroll { max-width: 100%; min-width: 0; overflow-x: auto; overscroll-behavior-x: contain; border: 1px solid #e5e5e5; border-radius: 10px; background: #fafafa; }
.tree-scroll:focus-visible { outline: 2px solid #2563eb; outline-offset: 2px; }
.tree-svg { display: block; max-width: none; margin-inline: auto; font-family: ui-monospace, SFMono-Regular, Consolas, monospace; }
.tree-edges line { stroke: #a3a3a3; stroke-width: 1.5; }
.tree-edges text { fill: #737373; font-size: 11px; text-anchor: middle; }
.tree-node circle, .tree-node rect { fill: #fff; stroke: #525252; stroke-width: 1.5; }
.tree-node text { fill: #171717; font-size: 15px; font-variant-numeric: tabular-nums; text-anchor: middle; dominant-baseline: middle; }
.tree-divider { stroke: #d4d4d4; stroke-width: 1; }
</style>
