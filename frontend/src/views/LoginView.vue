<script setup lang="ts">
// 登录页：账密登录 + 演示账号快捷填充
import { reactive, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import type { FormInstance, FormRules } from 'element-plus'
import { Lock, User } from '@element-plus/icons-vue'
import { useUserStore } from '@/stores/user'

const router = useRouter()
const route = useRoute()
const userStore = useUserStore()

const formRef = ref<FormInstance>()
const loading = ref(false)
const form = reactive({
  username: '',
  password: '',
})

const rules: FormRules = {
  username: [{ required: true, message: '请输入用户名', trigger: 'blur' }],
  password: [{ required: true, message: '请输入密码', trigger: 'blur' }],
}

// 演示账号（init_db.py 创建的种子数据）
const demoAccounts = [
  { username: 'employee01', password: 'employee123', label: '员工' },
  { username: 'manager01', password: 'manager123', label: '经理' },
  { username: 'finance01', password: 'finance123', label: '财务' },
  { username: 'admin', password: 'admin123', label: '管理员' },
]

function fillDemo(account: { username: string; password: string }) {
  form.username = account.username
  form.password = account.password
}

async function handleLogin() {
  await formRef.value?.validate()
  loading.value = true
  try {
    await userStore.login(form.username, form.password)
    ElMessage.success(`欢迎，${userStore.displayName}`)
    // 支持登录后回跳原页面（守卫带来的redirect参数）
    const redirect = (route.query.redirect as string) || '/dashboard'
    router.push(redirect)
  } catch {
    // 错误提示由 request 拦截器统一弹出
  } finally {
    loading.value = false
  }
}
</script>

<template>
  <div class="login-page">
    <div class="login-card">
      <div class="login-header">
        <el-icon :size="36" color="#409eff"><Coin /></el-icon>
        <h2>AI 财务报销审核系统</h2>
        <p class="sub">LangGraph 多 Agent 协同 · 智能风险审核</p>
      </div>

      <el-form ref="formRef" :model="form" :rules="rules" size="large" @keyup.enter="handleLogin">
        <el-form-item prop="username">
          <el-input v-model="form.username" placeholder="用户名" :prefix-icon="User" />
        </el-form-item>
        <el-form-item prop="password">
          <el-input
            v-model="form.password"
            type="password"
            show-password
            placeholder="密码"
            :prefix-icon="Lock"
          />
        </el-form-item>
        <el-form-item>
          <el-button type="primary" class="login-btn" :loading="loading" @click="handleLogin">
            登 录
          </el-button>
        </el-form-item>
      </el-form>

      <div class="demo-accounts">
        <span class="demo-title">演示账号（点击填充）：</span>
        <el-tag
          v-for="acc in demoAccounts"
          :key="acc.username"
          class="demo-tag"
          effect="plain"
          @click="fillDemo(acc)"
        >
          {{ acc.label }} {{ acc.username }}
        </el-tag>
      </div>
    </div>
  </div>
</template>

<style scoped lang="scss">
.login-page {
  height: 100vh;
  display: flex;
  align-items: center;
  justify-content: center;
  background: linear-gradient(135deg, #1f3a5f 0%, #0f2027 50%, #2c5364 100%);
}

.login-card {
  width: 400px;
  padding: 36px 32px 24px;
  background: #fff;
  border-radius: 12px;
  box-shadow: 0 12px 40px rgba(0, 0, 0, 0.25);

  .login-header {
    text-align: center;
    margin-bottom: 24px;

    h2 {
      margin: 8px 0 4px;
      font-size: 20px;
    }

    .sub {
      color: #909399;
      font-size: 13px;
      margin: 0;
    }
  }

  .login-btn {
    width: 100%;
  }

  .demo-accounts {
    margin-top: 8px;
    text-align: center;

    .demo-title {
      font-size: 12px;
      color: #909399;
    }

    .demo-tag {
      cursor: pointer;
      margin: 4px 2px 0;
    }
  }
}
</style>
