<template>
  <div
    class="report-view"
    :class="{
      'bento-layout': appStore.isBentoMode,
      'traditional-layout': appStore.isTraditionalMode
    }"
  >
    <header class="view-header">
      <h1>周期报告</h1>
      <!-- TODO: 添加日期选择器或其他报告筛选/操作 -->
    </header>

    <div class="report-content">
      <div
        v-if="isLoading"
        class="loading-message"
      >
        加载中...
      </div>
      <div
        v-if="error"
        class="error-message"
      >
        获取报告数据失败: {{ error }}
      </div>

      <div
        v-if="reportData && !isLoading && !error"
        class="report-details"
      >
        <h2>报告详情</h2>

        <div
          v-if="appStore.isBentoMode"
          class="bento-layout-content"
        >
          <!-- 配置信息 -->
          <BentoCard
            title="报告配置"
            :grid-span="{ colSpan: 2 }"
          >
            <p><strong>报告周期:</strong> {{ reportData.config?.report_period || '未知' }}</p>
            <p><strong>上次运行时间:</strong> {{ reportData.config?.last_run_time || '未知' }}</p>
            <p><strong>下次运行时间:</strong> {{ reportData.config?.next_run_time || '未知' }}</p>
            <p><strong>报告存储路径:</strong> {{ reportData.config?.report_storage_path || '未知' }}</p>
          </BentoCard>

          <!-- 使用统计概览 -->
          <BentoCard
            title="使用统计概览"
            :grid-span="{ colSpan: 1 }"
          >
            <p><strong>总请求数:</strong> {{ reportData.total_requests || 0 }}</p>
            <p><strong>总 token 数:</strong> {{ reportData.total_tokens || 0 }}</p>
            <p><strong>总成本估算:</strong> {{ reportData.total_cost_estimate || 0 }}</p>
            <!-- TODO: 添加更多概览统计 -->
          </BentoCard>

          <!-- 图表区域 -->
          <BentoCard
            title="使用趋势图表"
            :grid-span="{ colSpan: 3 }"
          >
            <canvas
              id="usageChart"
              width="400"
              height="200"
            />
            <!-- TODO: 集成 Chart.js 或其他图表库 -->
          </BentoCard>

          <!-- 详细数据表格 -->
          <BentoCard
            title="详细使用数据"
            :grid-span="{ colSpan: 3 }"
          >
            <table>
              <thead>
                <tr>
                  <th>日期</th>
                  <th>请求数</th>
                  <th>Token 数</th>
                  <th>成本估算</th>
                </tr>
              </thead>
              <tbody>
                <tr
                  v-for="(item, index) in reportData.usage_data"
                  :key="index"
                >
                  <td>{{ item.date }}</td>
                  <td>{{ item.requests }}</td>
                  <td>{{ item.tokens }}</td>
                  <td>{{ item.cost }}</td>
                </tr>
              </tbody>
            </table>
            <!-- TODO: 集成数据表格组件 -->
          </BentoCard>
        </div>

        <div
          v-else
          class="traditional-layout-content"
        >
          <!-- 传统视图下的报告详情 -->
          <!-- 配置信息 -->
          <section class="report-section">
            <h3>报告配置</h3>
            <p><strong>报告周期:</strong> {{ reportData.config?.report_period || '未知' }}</p>
            <p><strong>上次运行时间:</strong> {{ reportData.config?.last_run_time || '未知' }}</p>
            <p><strong>下次运行时间:</strong> {{ reportData.config?.next_run_time || '未知' }}</p>
            <p><strong>报告存储路径:</strong> {{ reportData.config?.report_storage_path || '未知' }}</p>
          </section>

          <!-- 使用统计概览 -->
          <section class="report-section">
            <h3>使用统计概览</h3>
            <p><strong>总请求数:</strong> {{ reportData.total_requests || 0 }}</p>
            <p><strong>总 token 数:</strong> {{ reportData.total_tokens || 0 }}</p>
            <p><strong>总成本估算:</strong> {{ reportData.total_cost_estimate || 0 }}</p>
            <!-- TODO: 添加更多概览统计 -->
          </section>

          <!-- 图表区域 -->
          <section class="report-section">
            <h3>使用趋势图表</h3>
            <canvas
              id="usageChart"
              width="400"
              height="200"
            />
            <!-- TODO: 集成 Chart.js 或其他图表库 -->
          </section>

          <!-- 详细数据表格 -->
          <section class="report-section">
            <h3>详细使用数据</h3>
            <table>
              <thead>
                <tr>
                  <th>日期</th>
                  <th>请求数</th>
                  <th>Token 数</th>
                  <th>成本估算</th>
                </tr>
              </thead>
              <tbody>
                <tr
                  v-for="(item, index) in reportData.usage_data"
                  :key="index"
                >
                  <td>{{ item.date }}</td>
                  <td>{{ item.requests }}</td>
                  <td>{{ item.tokens }}</td>
                  <td>{{ item.cost }}</td>
                </tr>
              </tbody>
            </table>
            <!-- TODO: 集成数据表格组件 -->
          </section>
        </div>
      </div>

      <div
        v-if="!reportData && !isLoading && !error"
        class="no-data-message"
      >
        <p>没有可用的周期报告数据。</p>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, onMounted, watch } from 'vue';
import apiService from '@/services/apiService'; // 导入 API 服务
import BentoCard from '@/components/common/BentoCard.vue'; // 导入 BentoCard
import { useAppStore } from '@/stores/appStore'; // 导入 appStore
import Chart from 'chart.js/auto'; // 导入 Chart.js


const isLoading = ref(false);
const error = ref(null);
const reportData = ref(null); // 用于存储报告数据

const appStore = useAppStore(); // 使用 appStore

const fetchReportData = async () => {
  isLoading.value = true;
  error.value = null;
  reportData.value = null; // 清空旧数据
  try {
    // 假设后端有一个 /report 接口返回报告数据
    const response = await apiService.getReport();
    if (response) {
      reportData.value = response;
      // 如果后端返回的数据没有 usage_data 或者 usage_data 为空，则使用模拟数据
      if (!response.usage_data || response.usage_data.length === 0) {
          reportData.value.usage_data = [
              { date: '2024-06-01', requests: 100, tokens: 50000, cost: 0.5 },
              { date: '2024-06-02', requests: 120, tokens: 60000, cost: 0.6 },
              { date: '2024-06-03', requests: 90, tokens: 45000, cost: 0.45 },
              { date: '2024-06-04', requests: 150, tokens: 75000, cost: 0.75 },
              { date: '2024-06-05', requests: 110, tokens: 55000, cost: 0.55 },
              { date: '2024-06-06', requests: 130, tokens: 65000, cost: 0.65 },
              { date: '2024-06-07', requests: 140, tokens: 70000, cost: 0.7 }
          ];
          error.value = '从服务器获取的报告数据为空或格式不正确，已使用模拟数据展示。';
      }
    } else {
       // 如果整个响应为空，则完全使用模拟数据
       reportData.value = createMockReportData();
       error.value = '从服务器获取的报告数据为空，已使用模拟数据展示。';
    }
  } catch (err) {
    // 即使出错也使用模拟数据
    reportData.value = createMockReportData();
    if (typeof err === 'object' && err !== null && err.message) {
        error.value = `错误 ${err.status || ''}: ${err.message} (已使用模拟数据)`;
    } else if (typeof err === 'object' && err !== null && err.detail) {
        error.value = `错误 ${err.status || ''}: ${err.detail} (已使用模拟数据)`;
    }
  } finally {
    isLoading.value = false;
  }
};

onMounted(() => {
  fetchReportData();
});

// 创建模拟报告数据的函数
const createMockReportData = () => {
    return {
        config: {
            report_period: '月度',
            last_run_time: '2024-05-31 23:59:59',
            next_run_time: '2024-06-30 23:59:59',
            report_storage_path: '/reports/monthly'
        },
        total_requests: 12345,
        total_tokens: 6789000,
        total_cost_estimate: 123.45,
        usage_data: [
            { date: '2024-06-01', requests: 100, tokens: 50000, cost: 0.5 },
            { date: '2024-06-02', requests: 120, tokens: 60000, cost: 0.6 },
            { date: '2024-06-03', requests: 90, tokens: 45000, cost: 0.45 },
            { date: '2024-06-04', requests: 150, tokens: 75000, cost: 0.75 },
            { date: '2024-06-05', requests: 110, tokens: 55000, cost: 0.55 },
            { date: '2024-06-06', requests: 130, tokens: 65000, cost: 0.65 },
            { date: '2024-06-07', requests: 140, tokens: 70000, cost: 0.7 }
        ]
    };
};

// 监听 reportData 的变化，以便在数据加载后创建图表
watch(reportData, (newReportData) => {
  if (newReportData && newReportData.usage_data) {
    renderChart(newReportData.usage_data);
  }
}, { immediate: false });

// 用于存储 Chart 实例
let chartInstance = null;
const renderChart = (usageData) => {
  const ctx = document.getElementById('usageChart');
  if (!ctx) {
    return;
  }

  // 准备图表数据
  const labels = usageData.map(item => item.date);
  const requestData = usageData.map(item => item.requests);
  const tokenData = usageData.map(item => item.tokens);

  // 销毁旧图表实例，避免重复渲染和内存泄漏
  if (chartInstance) {
    chartInstance.destroy();
  }

  chartInstance = new Chart(ctx, { // 将新实例赋值给 chartInstance
    type: 'line', // 折线图
    data: {
      labels: labels, // 日期作为标签
      datasets: [
        {
          label: '请求数', // 数据集标签
          data: requestData, // 请求数数据
          borderColor: '#007bff', // 蓝色线条
          backgroundColor: 'rgba(0, 123, 255, 0.2)', // 蓝色填充
          tension: 0.1, // 曲线平滑度
          fill: true // 填充区域
        },
        {
          label: 'Token 数', // 数据集标签
          data: tokenData, // Token 数数据
          borderColor: '#28a745', // 绿色线条
          backgroundColor: 'rgba(40, 167, 69, 0.2)', // 绿色填充
          tension: 0.1, // 曲线平滑度
          fill: true // 填充区域
        }
      ]
    },
    options: {
      responsive: true, // 响应式
      maintainAspectRatio: false, // 不保持宽高比，允许容器控制大小
      scales: {
        y: {
          beginAtZero: true, // Y轴从0开始
          title: {
            display: true,
            text: '数量' // Y轴标题
          }
        },
        x: {
            title: {
                display: true,
                text: '日期' // X轴标题
            }
        }
      },
      plugins: {
        legend: {
          display: true, // 显示图例
          position: 'top', // 图例位置
        },
        tooltip: {
          enabled: true // 启用工具提示
        }
      }
    }
  });
};
</script>

<style scoped>
.report-view {
  padding: 20px; /* 增加内边距 */
}

.view-header {
  margin-bottom: 30px; /* 增加底部外边距 */
  text-align: center; /* 标题居中 */
}

.view-header h1 {
  font-size: 28px; /* 调整标题大小 */
  color: #333;
  margin: 0; /* 移除默认 margin */
}

.report-content {
  width: 100%;
}

.report-details h2 {
    font-size: 24px;
    color: #333;
    margin-bottom: 20px;
    text-align: center;
}

/* 加载和错误消息样式 */
.loading-message, .error-message, .no-data-message {
    text-align: center;
    font-size: 1.1em;
    color: #555;
    margin-top: 50px;
}

.error-message {
    color: #dc3545;
}

/* BentoCard 在报告详情中的样式调整 */
.report-details .bento-card {
    margin-bottom: 20px; /* 卡片之间的间距 */
}

.report-details .bento-card p {
    margin: 0.5rem 0;
    font-size: 1em;
    color: #555;
}

.report-details .bento-card strong {
    color: #333;
}

/* 响应式调整 */
@media (max-width: 768px) {
  /* 根据需要为小屏幕调整样式 */
}
</style>

<!-- Traditional Layout Styles -->
<style scoped>
/* 当父布局为 traditional-layout 时应用的样式 */
.traditional-layout .report-details {
  /* 在传统视图下，让各个部分垂直堆叠 */
  display: block;
}

.traditional-layout .report-details .bento-card {
  /* 移除 Bento 风格 */
  background: none;
  border: none; /* 可以根据需要添加简单的边框，例如 border: 1px solid #eee; */
  box-shadow: none;
  border-radius: 0;
  padding: 15px 0; /* 调整内边距，移除左右，保留上下 */
  margin-bottom: 25px; /* 增加块之间的垂直间距 */
  backdrop-filter: none; /* 移除毛玻璃效果 */
  /* 如果 BentoCard 内部有特定的 header/content 结构，可能需要进一步调整 */
}

/* 调整传统视图下卡片内的标题样式 */
/* 注意：这假设 BentoCard 内部标题可以通过 h3 或类似选择器访问 */
/* 如果 BentoCard 内部结构不同，需要调整此选择器 */
.traditional-layout .report-details .bento-card ::v-deep(h3), /* 尝试访问 BentoCard 内部标题 */
.traditional-layout .report-details .bento-card > :first-child /* 或者假设标题是第一个子元素 */
 {
  font-size: 20px; /* 调整标题大小 */
  color: #333;
  margin-bottom: 10px;
  padding-bottom: 5px;
  border-bottom: 1px solid #eee; /* 添加分隔线 */
  font-weight: bold; /* 加粗标题 */
}

/* 调整传统视图下卡片内容的样式 */
.traditional-layout .report-details .bento-card p {
  font-size: 0.95em; /* 可以微调字体大小 */
  color: #444; /* 可以调整字体颜色 */
  margin: 0.4rem 0;
}

.traditional-layout .report-details .bento-card strong {
  color: #111; /* 加深强调文本颜色 */
}

/* 调整传统视图下的主标题 */
.traditional-layout .view-header h1 {
    font-size: 26px; /* 可以微调主标题大小 */
    text-align: left; /* 标题左对齐 */
    border-bottom: 2px solid #ddd; /* 添加下划线 */
    padding-bottom: 10px;
}

/* 调整传统视图下的报告详情标题 */
.traditional-layout .report-details h2 {
    text-align: left;
    font-size: 22px;
    border-bottom: none; /* 移除详情标题的下划线，让卡片标题的下划线更突出 */
    margin-bottom: 15px;
}

/* 传统视图下的表格样式 */
.traditional-layout .report-details table {
  width: 100%;
  border-collapse: collapse; /* 合并边框 */
  margin-top: 15px; /* 增加与上方元素的间距 */
  box-shadow: 0 1px 3px rgba(0, 0, 0, 0.1); /* 添加柔和阴影 */
  background-color: #fff; /* 白色背景 */
  border-radius: 6px; /* 轻微圆角 */
  overflow: hidden; /* 配合圆角 */
  border: 1px solid #ddd; /* 添加外边框 */
}

.traditional-layout .report-details th,
.traditional-layout .report-details td {
  padding: 12px 15px; /* 调整单元格内边距 */
  text-align: left;
  border-bottom: 1px solid #e0e0e0; /* 稍微柔和的底部边框 */
  vertical-align: middle; /* 垂直居中对齐 */
}

.traditional-layout .report-details th {
  background-color: #f7f7f7; /* 表头背景色 */
  font-weight: 600; /* 加粗字体 */
  color: #333; /* 字体颜色 */
  white-space: nowrap; /* 防止表头换行 */
}

.traditional-layout .report-details tbody tr:hover {
    background-color: #f0f8ff; /* 行悬停背景色 */
}

/* 响应式调整 */
@media (max-width: 768px) {
   .traditional-layout .report-details th,
   .traditional-layout .report-details td {
       padding: 10px 8px; /* 小屏幕下减小内边距 */
       font-size: 0.9em; /* 小屏幕下减小字体 */
   }
}
</style>
