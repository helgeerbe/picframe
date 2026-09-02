<script setup lang="ts">
import { computed } from 'vue'
import { ArrowDownIcon, ArrowUpIcon, PlusIcon, TrashIcon } from '@heroicons/vue/24/outline'

interface SortOption {
  key: string
  label: string
}

interface SortRule {
  column: string
  direction: 'ASC' | 'DESC'
}

const props = defineProps<{
  modelValue: string
  columns: SortOption[]
}>()

const emit = defineEmits<{
  'update:modelValue': [value: string]
}>()

const fallbackColumns = [
  'fname',
  'exif_datetime',
  'last_modified',
  'rating',
  'location',
  'tags',
  'width',
  'height',
  'displayed_count',
  'last_displayed'
].map(key => ({ key, label: key.replaceAll('_', ' ') }))

const availableColumns = computed(() => (props.columns.length ? props.columns : fallbackColumns))

function parseRules(): SortRule[] {
  return (props.modelValue || '')
    .split(',')
    .map(part => part.trim())
    .filter(Boolean)
    .map(part => {
      const [column, rawDirection] = part.split(/\s+/)
      const direction: 'ASC' | 'DESC' = rawDirection?.toUpperCase() === 'DESC' ? 'DESC' : 'ASC'
      return {
        column,
        direction
      }
    })
    .filter(rule => availableColumns.value.some(column => column.key === rule.column))
}

function save(rules: SortRule[]) {
  emit('update:modelValue', rules.map(rule => `${rule.column} ${rule.direction}`).join(', '))
}

function updateRule(index: number, patch: Partial<SortRule>) {
  const rules = parseRules()
  rules[index] = { ...rules[index], ...patch }
  save(rules)
}

function addRule() {
  const column = availableColumns.value[0]?.key || 'fname'
  save([...parseRules(), { column, direction: 'ASC' }])
}

function removeRule(index: number) {
  save(parseRules().filter((_rule, ruleIndex) => ruleIndex !== index))
}

function moveRule(index: number, direction: -1 | 1) {
  const rules = parseRules()
  const nextIndex = index + direction
  if (nextIndex < 0 || nextIndex >= rules.length) return
  const [rule] = rules.splice(index, 1)
  rules.splice(nextIndex, 0, rule)
  save(rules)
}
</script>

<template>
  <div class="space-y-3">
    <div
      v-for="(rule, index) in parseRules()"
      :key="`${rule.column}-${index}`"
      class="grid grid-cols-[minmax(0,1fr)_7rem_auto] gap-2"
    >
      <select
        :value="rule.column"
        class="rounded-lg border-gray-300 bg-white px-3 py-2 text-sm text-gray-900 shadow-sm focus:border-indigo-500 focus:ring-indigo-500 dark:border-gray-600 dark:bg-gray-700 dark:text-white"
        @change="updateRule(index, { column: ($event.target as HTMLSelectElement).value })"
      >
        <option v-for="column in availableColumns" :key="column.key" :value="column.key">
          {{ column.label }}
        </option>
      </select>
      <select
        :value="rule.direction"
        class="rounded-lg border-gray-300 bg-white px-3 py-2 text-sm text-gray-900 shadow-sm focus:border-indigo-500 focus:ring-indigo-500 dark:border-gray-600 dark:bg-gray-700 dark:text-white"
        @change="
          updateRule(index, {
            direction: ($event.target as HTMLSelectElement).value as 'ASC' | 'DESC'
          })
        "
      >
        <option value="ASC">ASC</option>
        <option value="DESC">DESC</option>
      </select>
      <div class="flex gap-1">
        <button
          type="button"
          class="rounded-lg p-2 text-gray-500 hover:bg-gray-100 dark:hover:bg-gray-700"
          @click="moveRule(index, -1)"
        >
          <ArrowUpIcon class="h-4 w-4" />
        </button>
        <button
          type="button"
          class="rounded-lg p-2 text-gray-500 hover:bg-gray-100 dark:hover:bg-gray-700"
          @click="moveRule(index, 1)"
        >
          <ArrowDownIcon class="h-4 w-4" />
        </button>
        <button
          type="button"
          class="rounded-lg p-2 text-red-600 hover:bg-red-50 dark:hover:bg-red-500/10"
          @click="removeRule(index)"
        >
          <TrashIcon class="h-4 w-4" />
        </button>
      </div>
    </div>
    <button
      type="button"
      class="inline-flex items-center rounded-lg border border-gray-300 px-3 py-2 text-sm font-medium text-gray-700 hover:bg-gray-50 dark:border-gray-600 dark:text-gray-300 dark:hover:bg-gray-700"
      @click="addRule"
    >
      <PlusIcon class="mr-2 h-4 w-4" />
      Add sort rule
    </button>
  </div>
</template>
