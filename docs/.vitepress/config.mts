import { defineConfig } from 'vitepress'

export default defineConfig({
  title: "Atlas",
  description: "践行 Project Harness 的全流程 AI 编程工作流治理引擎",
  lang: 'zh-CN',
  base: '/atlas/',
  cleanUrls: true,
  lastUpdated: true,

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
      { text: '核心架构', link: '/concepts/architecture' },
      { text: '独门重器', link: '/innovations/e2e-console' },
      { text: '机器门禁', link: '/gates/iron-gates' },
      { text: '技能生态', link: '/ecosystem/skills' },
      { text: '社区交流', link: '/guide/community' },
      { text: 'RFC 协同', link: '/guide/contributing' },
      { text: 'v0.1.0-beta.4', link: 'https://github.com/sunwenzhe-git/atlas/releases' }
    ],

    socialLinks: [
      { icon: 'github', link: 'https://github.com/sunwenzhe-git/atlas' }
    ],

    sidebar: [
      {
        text: '🏛️ 核心架构',
        collapsed: false,
        items: [
          { text: '践行 Project Harness (两层正交)', link: '/concepts/architecture' },
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
          { text: '破局 Vibe Coding', link: '/guide/how-it-works' }
        ]
      },
      {
        text: '⚡ 独门重器',
        collapsed: false,
        items: [
          { text: 'E2E 用例评审控制台', link: '/innovations/e2e-console' },
          { text: '代码图谱 (Code Graph) 逆向', link: '/innovations/code-graph' },
          { text: '变异证明 (Mutation Proving)', link: '/innovations/mutation-proving' },
          { text: '硬核断言与累加链解耦', link: '/innovations/assertions' },
          { text: '流水线自感知上报', link: '/innovations/self-reporting' }
        ]
      },
      {
        text: '🛡️ 机器门禁',
        collapsed: false,
        items: [
          { text: '铁血门禁总览 (The Iron Gates)', link: '/gates/iron-gates' }
        ]
      },
      {
        text: '🧰 技能与生态',
        collapsed: false,
        items: [
          { text: '自带技能全家桶', link: '/ecosystem/skills' }
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
