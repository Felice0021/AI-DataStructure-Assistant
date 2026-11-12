import { mount } from "@vue/test-utils"
import { createPinia, setActivePinia } from "pinia"
import { expect, it, vi } from "vitest"
import AuthPanel from "./AuthPanel.vue"

it("hides registration when the QA build disables it", () => {
  setActivePinia(createPinia())
  vi.stubEnv("VITE_REGISTRATION_ENABLED", "false")
  try {
    const wrapper = mount(AuthPanel)
    expect(wrapper.findAll("button.tab")).toHaveLength(1)
    expect(wrapper.text()).not.toContain("注册")
  } finally {
    vi.unstubAllEnvs()
  }
})
