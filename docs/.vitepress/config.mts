import { defineConfig } from 'vitepress'

export default defineConfig({
  title: "Atlas",
  description: "践行 Project Harness 的全流程 AI 编程工作流治理引擎",
  lang: 'zh-CN',
  base: '/atlas/',
  cleanUrls: true,
  lastUpdated: true,

  head: [
    ['link', { rel: 'icon', href: '/atlas/images/e2e-console.png' }],
    ['meta', { property: 'og:site_name', content: 'Atlas' }],
    ['meta', { property: 'og:type', content: 'article' }],
    ['meta', { property: 'og:image', content: 'https://sunwenzhe-git.github.io/atlas/images/e2e-console.png' }],
    ['meta', { name: 'twitter:card', content: 'summary_large_image' }],
    ['meta', { name: 'twitter:image', content: 'https://sunwenzhe-git.github.io/atlas/images/e2e-console.png' }],
  ],

  transformHead({ pageData }) {
    const title = pageData.title
      ? `${pageData.title} | Atlas`
      : 'Atlas — 践行 Project Harness 的全流程 AI 编程工作流治理引擎'
    const description = pageData.description || '践行 Project Harness 的全流程 AI 编程工作流治理引擎'
    const pagePath = pageData.relativePath.replace(/((^|\/)index)?\.md$/, '$2').replace(/\.md$/, '')
    const url = `https://sunwenzhe-git.github.io/atlas/${pagePath}`

    return [
      ['meta', { property: 'og:title', content: title }],
      ['meta', { property: 'og:description', content: description }],
      ['meta', { property: 'og:url', content: url }],
      ['meta', { name: 'twitter:title', content: title }],
      ['meta', { name: 'twitter:description', content: description }],
    ]
  },

  themeConfig: {
    siteTitle: "Atlas",
    logo: '/images/e2e-console.png',

    search: {
      provider: 'local',
      options: {
        translations: {
          button: {
            buttonText: '搜索文档',
            buttonAriaLabel: '搜索文档'
          },
          modal: {
            noResultsText: '无法找到相关结果',
            resetButtonTitle: '清除查询条件',
            footer: {
              selectText: '选择',
              navigateText: '切换',
              closeText: '关闭'
            }
          }
        }
      }
    },

    nav: [
      { text: '快速开始', link: '/guide/quick-start' },
      { text: '框架横评', link: '/guide/comparison' },
      { text: 'Token 工程', link: '/guide/token-engineering' },
      { text: '核心架构', link: '/concepts/architecture' },
      { text: '设计方案', link: '/design/overview' },
      { text: '创新设计', link: '/innovations/e2e-console' },
      { text: '门禁系统', link: '/gates/iron-gates' },
      { text: '技能生态', link: '/ecosystem/skills' },
      { text: '社区交流', link: '/guide/community' },
      { text: '更新日志', link: '/guide/changelog' },
      { text: 'v0.1.0-beta.30', link: 'https://github.com/sunwenzhe-git/atlas/releases' }
    ],

    socialLinks: [
      { icon: 'github', link: 'https://github.com/sunwenzhe-git/atlas' }
    ],

    sidebar: [
      {
        text: '📐 设计方案',
        collapsed: false,
        items: [
          { text: '全流程设计总览', link: '/design/overview' },
          { text: '结构（逆向）环设计', link: '/design/structure-ring' },
          { text: '产品（PRD）环设计', link: '/design/prd-ring' },
          { text: 'E2E 环设计', link: '/design/e2e-ring' },
          { text: '跨项目分发设计', link: '/design/distribution' }
        ]
      },
      {
        text: '🏛️ 核心架构',
        collapsed: false,
        items: [
          { text: '践行 Project Harness (双线束)', link: '/concepts/architecture' },
          { text: '三环资产体系', link: '/concepts/rings' },
          { text: '唯一编排件 (apply)', link: '/concepts/apply' },
          { text: '独立审查：四类实例', link: '/concepts/review' },
          { text: '产物落点与生命周期', link: '/concepts/layout' }
        ]
      },
      {
        text: '🚀 开始使用',
        collapsed: false,
        items: [
          { text: '30 秒快速上手', link: '/guide/quick-start' },
          { text: '存量项目接入指南 (adopt)', link: '/guide/legacy-adoption' },
          { text: '主流框架横评与选型', link: '/guide/comparison' },
          { text: 'Token 节流与上下文工程', link: '/guide/token-engineering' },
          { text: '破局 Vibe Coding', link: '/guide/how-it-works' },
          { text: '更新日志 (Changelog)', link: '/guide/changelog' }
        ]
      },
      {
        text: '⚡ 创新设计',
        collapsed: false,
        items: [
          { text: 'E2E 用例评审控制台', link: '/innovations/e2e-console' },
          { text: '代码图谱 (Code Graph) 逆向', link: '/innovations/code-graph' },
          { text: '变异证明 (Mutation Proving)', link: '/innovations/mutation-proving' },
          { text: '断言规范与累加链解耦', link: '/innovations/assertions' },
          { text: '流水线自感知上报', link: '/innovations/self-reporting' }
        ]
      },
      {
        text: '🛡️ 门禁系统',
        collapsed: false,
        items: [
          { text: '门禁系统总览 (Gates)', link: '/gates/iron-gates' }
        ]
      },
      {
        text: '🧰 技能与生态',
        collapsed: false,
        items: [
          { text: '内置技能与 Agents', link: '/ecosystem/skills' },
          { text: 'Pi Agent 扩展实践', link: '/ecosystem/pi-extensions' }
        ]
      },
      {
        text: '🤝 贡献与协同',
        collapsed: false,
        items: [
          { text: '钉钉交流群', link: '/guide/community' },
          { text: '流水线 RFC 协同机制', link: '/guide/contributing' }
        ]
      }
    ],

    outline: {
      level: [2, 3],
      label: '本页目录'
    },

    footer: {
      message: 'Released under the Apache-2.0 License.',
      copyright: 'Copyright © 2026 Atlas Authors. Governed by machines.'
    },

    docFooter: {
      prev: '上一篇',
      next: '下一篇'
    }
  }
})
