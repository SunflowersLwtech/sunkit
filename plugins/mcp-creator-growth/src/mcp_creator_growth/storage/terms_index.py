"""
Terms Index Manager
====================

Manages the terms glossary storage at `.mcp-sidecar/terms/`.
Provides operations for tracking shown terms and retrieving new ones.
"""

import json
from datetime import datetime
from pathlib import Path
from typing import Any
from collections import OrderedDict

from ..debug import server_debug_log as debug_log


# Built-in terms glossary organized by domain
# Each term has: term (EN), term_cn (中文), definition_en, definition_cn
TERMS_GLOSSARY: dict[str, list[dict[str, str]]] = {
    "programming_basics": [
        {
            "term": "Variable",
            "term_cn": "变量",
            "definition_en": "A named storage location in memory that holds a value which can be changed during program execution.",
            "definition_cn": "内存中用于存储值的命名位置，其值在程序执行过程中可以被修改。"
        },
        {
            "term": "Function",
            "term_cn": "函数",
            "definition_en": "A reusable block of code that performs a specific task and can be called with arguments.",
            "definition_cn": "一段可重复使用的代码块，用于执行特定任务，可以通过参数调用。"
        },
        {
            "term": "Class",
            "term_cn": "类",
            "definition_en": "A blueprint for creating objects that defines properties and methods shared by all instances.",
            "definition_cn": "创建对象的蓝图，定义了所有实例共享的属性和方法。"
        },
        {
            "term": "Object",
            "term_cn": "对象",
            "definition_en": "An instance of a class containing data (attributes) and behavior (methods).",
            "definition_cn": "类的实例，包含数据（属性）和行为（方法）。"
        },
        {
            "term": "Method",
            "term_cn": "方法",
            "definition_en": "A function defined within a class that operates on instances of that class.",
            "definition_cn": "定义在类中的函数，用于操作该类的实例。"
        },
        {
            "term": "Parameter",
            "term_cn": "参数",
            "definition_en": "A variable in a function definition that receives a value when the function is called.",
            "definition_cn": "函数定义中的变量，在函数调用时接收传入的值。"
        },
        {
            "term": "Argument",
            "term_cn": "实参",
            "definition_en": "The actual value passed to a function when it is called.",
            "definition_cn": "调用函数时传递给函数的实际值。"
        },
        {
            "term": "Return Value",
            "term_cn": "返回值",
            "definition_en": "The value that a function sends back to the code that called it.",
            "definition_cn": "函数执行完成后返回给调用代码的值。"
        },
        {
            "term": "Loop",
            "term_cn": "循环",
            "definition_en": "A control structure that repeats a block of code while a condition is true or for a set number of iterations.",
            "definition_cn": "一种控制结构，在条件为真或达到指定次数时重复执行代码块。"
        },
        {
            "term": "Conditional",
            "term_cn": "条件语句",
            "definition_en": "A statement that executes different code blocks based on whether a condition is true or false.",
            "definition_cn": "根据条件真假执行不同代码块的语句。"
        },
    ],
    "data_structures": [
        {
            "term": "Array",
            "term_cn": "数组",
            "definition_en": "A data structure that stores elements of the same type in contiguous memory locations.",
            "definition_cn": "一种数据结构，在连续的内存位置存储相同类型的元素。"
        },
        {
            "term": "List",
            "term_cn": "列表",
            "definition_en": "An ordered collection of elements that can be of different types and supports dynamic sizing.",
            "definition_cn": "有序的元素集合，可以包含不同类型的元素，支持动态调整大小。"
        },
        {
            "term": "Dictionary",
            "term_cn": "字典",
            "definition_en": "A collection of key-value pairs where each key is unique and maps to a value.",
            "definition_cn": "键值对的集合，每个键是唯一的并映射到一个值。"
        },
        {
            "term": "Hash Map",
            "term_cn": "哈希表",
            "definition_en": "A data structure that uses a hash function to map keys to values for fast lookup.",
            "definition_cn": "使用哈希函数将键映射到值的数据结构，支持快速查找。"
        },
        {
            "term": "Stack",
            "term_cn": "栈",
            "definition_en": "A Last-In-First-Out (LIFO) data structure where elements are added and removed from the top.",
            "definition_cn": "后进先出（LIFO）数据结构，元素从顶部添加和移除。"
        },
        {
            "term": "Queue",
            "term_cn": "队列",
            "definition_en": "A First-In-First-Out (FIFO) data structure where elements are added at the back and removed from the front.",
            "definition_cn": "先进先出（FIFO）数据结构，元素从后端添加，从前端移除。"
        },
        {
            "term": "Tree",
            "term_cn": "树",
            "definition_en": "A hierarchical data structure with a root node and child nodes forming a parent-child relationship.",
            "definition_cn": "具有根节点和子节点的层次数据结构，形成父子关系。"
        },
        {
            "term": "Graph",
            "term_cn": "图",
            "definition_en": "A data structure consisting of nodes (vertices) connected by edges, representing relationships.",
            "definition_cn": "由节点（顶点）和边连接组成的数据结构，用于表示关系。"
        },
        {
            "term": "Linked List",
            "term_cn": "链表",
            "definition_en": "A linear data structure where elements are stored in nodes connected by pointers.",
            "definition_cn": "线性数据结构，元素存储在通过指针连接的节点中。"
        },
        {
            "term": "Set",
            "term_cn": "集合",
            "definition_en": "An unordered collection of unique elements with no duplicate values.",
            "definition_cn": "不包含重复值的无序唯一元素集合。"
        },
    ],
    "algorithms": [
        {
            "term": "Algorithm",
            "term_cn": "算法",
            "definition_en": "A step-by-step procedure for solving a problem or accomplishing a task.",
            "definition_cn": "解决问题或完成任务的分步骤过程。"
        },
        {
            "term": "Time Complexity",
            "term_cn": "时间复杂度",
            "definition_en": "A measure of how the running time of an algorithm grows relative to input size.",
            "definition_cn": "衡量算法运行时间如何随输入大小增长的指标。"
        },
        {
            "term": "Space Complexity",
            "term_cn": "空间复杂度",
            "definition_en": "A measure of how much memory an algorithm uses relative to input size.",
            "definition_cn": "衡量算法使用内存量如何随输入大小变化的指标。"
        },
        {
            "term": "Big O Notation",
            "term_cn": "大O表示法",
            "definition_en": "A mathematical notation describing the upper bound of an algorithm's complexity.",
            "definition_cn": "描述算法复杂度上界的数学表示法。"
        },
        {
            "term": "Recursion",
            "term_cn": "递归",
            "definition_en": "A technique where a function calls itself to solve smaller instances of the same problem.",
            "definition_cn": "函数调用自身来解决同一问题的较小实例的技术。"
        },
        {
            "term": "Binary Search",
            "term_cn": "二分查找",
            "definition_en": "An efficient search algorithm that repeatedly divides a sorted array in half to find a target value.",
            "definition_cn": "一种高效的搜索算法，反复将排序数组分成两半以查找目标值。"
        },
        {
            "term": "Sorting",
            "term_cn": "排序",
            "definition_en": "The process of arranging elements in a specific order (ascending or descending).",
            "definition_cn": "按特定顺序（升序或降序）排列元素的过程。"
        },
        {
            "term": "Dynamic Programming",
            "term_cn": "动态规划",
            "definition_en": "An optimization technique that solves complex problems by breaking them into overlapping subproblems.",
            "definition_cn": "一种优化技术，通过将复杂问题分解为重叠子问题来解决。"
        },
        {
            "term": "Greedy Algorithm",
            "term_cn": "贪心算法",
            "definition_en": "An algorithm that makes the locally optimal choice at each step hoping to find a global optimum.",
            "definition_cn": "在每一步选择局部最优解，期望找到全局最优解的算法。"
        },
        {
            "term": "Divide and Conquer",
            "term_cn": "分治法",
            "definition_en": "A strategy that divides a problem into smaller subproblems, solves them, and combines the results.",
            "definition_cn": "将问题分解为较小子问题、分别解决并合并结果的策略。"
        },
    ],
    "software_design": [
        {
            "term": "API",
            "term_cn": "应用程序接口",
            "definition_en": "Application Programming Interface - a set of protocols for building and integrating software.",
            "definition_cn": "应用程序编程接口 - 用于构建和集成软件的协议集合。"
        },
        {
            "term": "Abstraction",
            "term_cn": "抽象",
            "definition_en": "Hiding complex implementation details while exposing only essential features.",
            "definition_cn": "隐藏复杂的实现细节，只暴露必要的功能。"
        },
        {
            "term": "Encapsulation",
            "term_cn": "封装",
            "definition_en": "Bundling data and methods that operate on that data within a single unit (class).",
            "definition_cn": "将数据和操作数据的方法捆绑在单个单元（类）中。"
        },
        {
            "term": "Inheritance",
            "term_cn": "继承",
            "definition_en": "A mechanism where a class derives properties and behaviors from a parent class.",
            "definition_cn": "类从父类派生属性和行为的机制。"
        },
        {
            "term": "Polymorphism",
            "term_cn": "多态",
            "definition_en": "The ability of different classes to be treated as instances of the same class through a common interface.",
            "definition_cn": "通过公共接口将不同类视为同一类实例的能力。"
        },
        {
            "term": "Design Pattern",
            "term_cn": "设计模式",
            "definition_en": "A reusable solution to a commonly occurring problem in software design.",
            "definition_cn": "软件设计中常见问题的可重用解决方案。"
        },
        {
            "term": "Refactoring",
            "term_cn": "重构",
            "definition_en": "Restructuring existing code without changing its external behavior to improve readability and maintainability.",
            "definition_cn": "在不改变外部行为的情况下重构现有代码，以提高可读性和可维护性。"
        },
        {
            "term": "SOLID Principles",
            "term_cn": "SOLID原则",
            "definition_en": "Five design principles for writing maintainable object-oriented code: Single Responsibility, Open/Closed, Liskov Substitution, Interface Segregation, Dependency Inversion.",
            "definition_cn": "编写可维护面向对象代码的五个设计原则：单一职责、开放封闭、里氏替换、接口隔离、依赖倒置。"
        },
        {
            "term": "DRY Principle",
            "term_cn": "DRY原则",
            "definition_en": "Don't Repeat Yourself - a principle promoting code reuse and reducing redundancy.",
            "definition_cn": "不要重复自己 - 促进代码重用和减少冗余的原则。"
        },
        {
            "term": "Technical Debt",
            "term_cn": "技术债务",
            "definition_en": "The implied cost of future rework caused by choosing quick solutions over better approaches.",
            "definition_cn": "选择快速解决方案而非更好方案所导致的未来返工的隐含成本。"
        },
    ],
    "web_development": [
        {
            "term": "HTTP",
            "term_cn": "超文本传输协议",
            "definition_en": "HyperText Transfer Protocol - the foundation of data communication on the World Wide Web.",
            "definition_cn": "超文本传输协议 - 万维网上数据通信的基础。"
        },
        {
            "term": "REST",
            "term_cn": "表述性状态转移",
            "definition_en": "Representational State Transfer - an architectural style for designing networked applications.",
            "definition_cn": "表述性状态转移 - 设计网络应用程序的架构风格。"
        },
        {
            "term": "JSON",
            "term_cn": "JavaScript对象表示法",
            "definition_en": "JavaScript Object Notation - a lightweight data interchange format.",
            "definition_cn": "JavaScript对象表示法 - 一种轻量级数据交换格式。"
        },
        {
            "term": "DOM",
            "term_cn": "文档对象模型",
            "definition_en": "Document Object Model - a programming interface for web documents.",
            "definition_cn": "文档对象模型 - 用于Web文档的编程接口。"
        },
        {
            "term": "CORS",
            "term_cn": "跨源资源共享",
            "definition_en": "Cross-Origin Resource Sharing - a mechanism allowing web pages to request resources from another domain.",
            "definition_cn": "跨源资源共享 - 允许网页从另一个域请求资源的机制。"
        },
        {
            "term": "WebSocket",
            "term_cn": "WebSocket协议",
            "definition_en": "A protocol providing full-duplex communication channels over a single TCP connection.",
            "definition_cn": "通过单个TCP连接提供全双工通信通道的协议。"
        },
        {
            "term": "Frontend",
            "term_cn": "前端",
            "definition_en": "The client-side part of a web application that users interact with directly.",
            "definition_cn": "用户直接交互的Web应用程序的客户端部分。"
        },
        {
            "term": "Backend",
            "term_cn": "后端",
            "definition_en": "The server-side part of a web application that handles data processing and storage.",
            "definition_cn": "处理数据处理和存储的Web应用程序的服务器端部分。"
        },
        {
            "term": "Middleware",
            "term_cn": "中间件",
            "definition_en": "Software that acts as a bridge between different applications or components.",
            "definition_cn": "充当不同应用程序或组件之间桥梁的软件。"
        },
        {
            "term": "Authentication",
            "term_cn": "身份验证",
            "definition_en": "The process of verifying the identity of a user or system.",
            "definition_cn": "验证用户或系统身份的过程。"
        },
    ],
    "version_control": [
        {
            "term": "Git",
            "term_cn": "Git版本控制",
            "definition_en": "A distributed version control system for tracking changes in source code.",
            "definition_cn": "用于跟踪源代码更改的分布式版本控制系统。"
        },
        {
            "term": "Repository",
            "term_cn": "仓库",
            "definition_en": "A storage location for code and its version history.",
            "definition_cn": "存储代码及其版本历史的位置。"
        },
        {
            "term": "Commit",
            "term_cn": "提交",
            "definition_en": "A snapshot of changes saved to the version control history.",
            "definition_cn": "保存到版本控制历史的更改快照。"
        },
        {
            "term": "Branch",
            "term_cn": "分支",
            "definition_en": "A parallel version of a repository allowing independent development.",
            "definition_cn": "仓库的并行版本，允许独立开发。"
        },
        {
            "term": "Merge",
            "term_cn": "合并",
            "definition_en": "Combining changes from different branches into one.",
            "definition_cn": "将不同分支的更改合并为一个。"
        },
        {
            "term": "Pull Request",
            "term_cn": "拉取请求",
            "definition_en": "A request to merge code changes from one branch to another for review.",
            "definition_cn": "请求将代码更改从一个分支合并到另一个分支以供审查。"
        },
        {
            "term": "Conflict",
            "term_cn": "冲突",
            "definition_en": "A situation where changes in different branches cannot be automatically merged.",
            "definition_cn": "不同分支中的更改无法自动合并的情况。"
        },
        {
            "term": "Rebase",
            "term_cn": "变基",
            "definition_en": "Moving or combining commits to a new base commit.",
            "definition_cn": "将提交移动或合并到新的基础提交。"
        },
        {
            "term": "Stash",
            "term_cn": "暂存",
            "definition_en": "Temporarily storing uncommitted changes for later use.",
            "definition_cn": "临时存储未提交的更改以供以后使用。"
        },
        {
            "term": "Clone",
            "term_cn": "克隆",
            "definition_en": "Creating a local copy of a remote repository.",
            "definition_cn": "创建远程仓库的本地副本。"
        },
    ],
    "testing": [
        {
            "term": "Unit Test",
            "term_cn": "单元测试",
            "definition_en": "Testing individual components or functions in isolation.",
            "definition_cn": "独立测试单个组件或函数。"
        },
        {
            "term": "Integration Test",
            "term_cn": "集成测试",
            "definition_en": "Testing how different modules or services work together.",
            "definition_cn": "测试不同模块或服务如何协同工作。"
        },
        {
            "term": "E2E Test",
            "term_cn": "端到端测试",
            "definition_en": "End-to-End testing that validates the entire application flow.",
            "definition_cn": "验证整个应用程序流程的端到端测试。"
        },
        {
            "term": "TDD",
            "term_cn": "测试驱动开发",
            "definition_en": "Test-Driven Development - writing tests before writing the actual code.",
            "definition_cn": "测试驱动开发 - 在编写实际代码之前先编写测试。"
        },
        {
            "term": "Mock",
            "term_cn": "模拟对象",
            "definition_en": "A simulated object that mimics the behavior of real objects in testing.",
            "definition_cn": "在测试中模拟真实对象行为的模拟对象。"
        },
        {
            "term": "Code Coverage",
            "term_cn": "代码覆盖率",
            "definition_en": "A metric measuring the percentage of code executed during tests.",
            "definition_cn": "衡量测试期间执行代码百分比的指标。"
        },
        {
            "term": "Assertion",
            "term_cn": "断言",
            "definition_en": "A statement that checks if a condition is true during testing.",
            "definition_cn": "在测试期间检查条件是否为真的语句。"
        },
        {
            "term": "Regression Test",
            "term_cn": "回归测试",
            "definition_en": "Testing to ensure new changes don't break existing functionality.",
            "definition_cn": "确保新更改不会破坏现有功能的测试。"
        },
        {
            "term": "Fixture",
            "term_cn": "测试夹具",
            "definition_en": "Predefined data or state used to set up test environments.",
            "definition_cn": "用于设置测试环境的预定义数据或状态。"
        },
        {
            "term": "CI/CD",
            "term_cn": "持续集成/持续部署",
            "definition_en": "Continuous Integration/Continuous Deployment - automated testing and deployment pipelines.",
            "definition_cn": "持续集成/持续部署 - 自动化测试和部署流水线。"
        },
    ],
    "security": [
        {
            "term": "Encryption",
            "term_cn": "加密",
            "definition_en": "Converting data into a coded format to prevent unauthorized access.",
            "definition_cn": "将数据转换为编码格式以防止未经授权的访问。"
        },
        {
            "term": "Hashing",
            "term_cn": "哈希",
            "definition_en": "Converting data into a fixed-size string using a mathematical function.",
            "definition_cn": "使用数学函数将数据转换为固定大小的字符串。"
        },
        {
            "term": "SQL Injection",
            "term_cn": "SQL注入",
            "definition_en": "A code injection technique that exploits vulnerabilities in database queries.",
            "definition_cn": "利用数据库查询漏洞的代码注入技术。"
        },
        {
            "term": "XSS",
            "term_cn": "跨站脚本攻击",
            "definition_en": "Cross-Site Scripting - injecting malicious scripts into web pages.",
            "definition_cn": "跨站脚本攻击 - 将恶意脚本注入网页。"
        },
        {
            "term": "CSRF",
            "term_cn": "跨站请求伪造",
            "definition_en": "Cross-Site Request Forgery - tricking users into performing unintended actions.",
            "definition_cn": "跨站请求伪造 - 诱骗用户执行意外操作。"
        },
        {
            "term": "Token",
            "term_cn": "令牌",
            "definition_en": "A piece of data used to authenticate or authorize a user or request.",
            "definition_cn": "用于验证或授权用户或请求的数据片段。"
        },
        {
            "term": "OAuth",
            "term_cn": "开放授权",
            "definition_en": "An open standard for access delegation commonly used for token-based authentication.",
            "definition_cn": "用于访问委托的开放标准，常用于基于令牌的身份验证。"
        },
        {
            "term": "SSL/TLS",
            "term_cn": "安全套接层/传输层安全",
            "definition_en": "Cryptographic protocols for secure communication over networks.",
            "definition_cn": "用于网络安全通信的加密协议。"
        },
        {
            "term": "Vulnerability",
            "term_cn": "漏洞",
            "definition_en": "A weakness in a system that can be exploited by attackers.",
            "definition_cn": "系统中可被攻击者利用的弱点。"
        },
        {
            "term": "Sanitization",
            "term_cn": "数据清理",
            "definition_en": "Cleaning user input to remove potentially harmful content.",
            "definition_cn": "清理用户输入以移除潜在有害内容。"
        },
    ],
    "databases": [
        {
            "term": "Database",
            "term_cn": "数据库",
            "definition_en": "An organized collection of structured data stored and accessed electronically.",
            "definition_cn": "以电子方式存储和访问的结构化数据有组织集合。"
        },
        {
            "term": "SQL",
            "term_cn": "结构化查询语言",
            "definition_en": "Structured Query Language - used for managing and querying relational databases.",
            "definition_cn": "结构化查询语言 - 用于管理和查询关系数据库。"
        },
        {
            "term": "NoSQL",
            "term_cn": "非关系型数据库",
            "definition_en": "Non-relational databases designed for flexible, scalable data storage.",
            "definition_cn": "为灵活、可扩展数据存储设计的非关系型数据库。"
        },
        {
            "term": "Primary Key",
            "term_cn": "主键",
            "definition_en": "A unique identifier for each record in a database table.",
            "definition_cn": "数据库表中每条记录的唯一标识符。"
        },
        {
            "term": "Foreign Key",
            "term_cn": "外键",
            "definition_en": "A field that links to the primary key of another table.",
            "definition_cn": "链接到另一个表主键的字段。"
        },
        {
            "term": "Index",
            "term_cn": "索引",
            "definition_en": "A data structure that improves the speed of data retrieval operations.",
            "definition_cn": "提高数据检索操作速度的数据结构。"
        },
        {
            "term": "Transaction",
            "term_cn": "事务",
            "definition_en": "A sequence of database operations treated as a single unit of work.",
            "definition_cn": "作为单个工作单元处理的一系列数据库操作。"
        },
        {
            "term": "ACID",
            "term_cn": "ACID特性",
            "definition_en": "Atomicity, Consistency, Isolation, Durability - properties ensuring reliable transactions.",
            "definition_cn": "原子性、一致性、隔离性、持久性 - 确保可靠事务的特性。"
        },
        {
            "term": "ORM",
            "term_cn": "对象关系映射",
            "definition_en": "Object-Relational Mapping - a technique for converting data between incompatible type systems.",
            "definition_cn": "对象关系映射 - 在不兼容类型系统之间转换数据的技术。"
        },
        {
            "term": "Query",
            "term_cn": "查询",
            "definition_en": "A request for data or information from a database.",
            "definition_cn": "从数据库请求数据或信息。"
        },
    ],
    "devops": [
        {
            "term": "DevOps",
            "term_cn": "开发运维",
            "definition_en": "A set of practices combining software development and IT operations.",
            "definition_cn": "结合软件开发和IT运维的一套实践。"
        },
        {
            "term": "Container",
            "term_cn": "容器",
            "definition_en": "A lightweight, portable unit that packages code and its dependencies together.",
            "definition_cn": "将代码及其依赖项打包在一起的轻量级、可移植单元。"
        },
        {
            "term": "Docker",
            "term_cn": "Docker容器",
            "definition_en": "A platform for developing, shipping, and running applications in containers.",
            "definition_cn": "用于在容器中开发、交付和运行应用程序的平台。"
        },
        {
            "term": "Kubernetes",
            "term_cn": "Kubernetes",
            "definition_en": "An open-source container orchestration platform for automating deployment and scaling.",
            "definition_cn": "用于自动化部署和扩展的开源容器编排平台。"
        },
        {
            "term": "Microservices",
            "term_cn": "微服务",
            "definition_en": "An architectural style where applications are built as small, independent services.",
            "definition_cn": "将应用程序构建为小型独立服务的架构风格。"
        },
        {
            "term": "Load Balancer",
            "term_cn": "负载均衡器",
            "definition_en": "A device or software that distributes network traffic across multiple servers.",
            "definition_cn": "在多个服务器之间分配网络流量的设备或软件。"
        },
        {
            "term": "Deployment",
            "term_cn": "部署",
            "definition_en": "The process of making an application available for use.",
            "definition_cn": "使应用程序可供使用的过程。"
        },
        {
            "term": "Monitoring",
            "term_cn": "监控",
            "definition_en": "Observing and tracking system performance and health in real-time.",
            "definition_cn": "实时观察和跟踪系统性能和健康状况。"
        },
        {
            "term": "Logging",
            "term_cn": "日志记录",
            "definition_en": "Recording events and activities in a system for debugging and auditing.",
            "definition_cn": "记录系统中的事件和活动以用于调试和审计。"
        },
        {
            "term": "Infrastructure as Code",
            "term_cn": "基础设施即代码",
            "definition_en": "Managing infrastructure through configuration files rather than manual processes.",
            "definition_cn": "通过配置文件而非手动流程管理基础设施。"
        },
    ],
}


class TermsIndexManager:
    """
    Manages terms tracking to ensure no term is shown twice.

    Storage structure:
    {project_root}/.mcp-sidecar/terms/
    └── shown.json         # Record of shown term IDs
    """

    def __init__(self, project_directory: str):
        """
        Initialize the terms index manager.

        Args:
            project_directory: The project root directory
        """
        self.project_directory = Path(project_directory).resolve()
        self.storage_dir = self.project_directory / ".mcp-sidecar" / "terms"
        self.shown_file = self.storage_dir / "shown.json"

        # Ensure storage directory exists
        self.storage_dir.mkdir(parents=True, exist_ok=True)

        # Load shown terms
        self._shown = self._load_shown()

        # Build a flat list of all terms with unique IDs
        self._all_terms = self._build_terms_index()

    def _load_shown(self) -> dict[str, Any]:
        """Load the shown terms record."""
        if self.shown_file.exists():
            try:
                with open(self.shown_file, "r", encoding="utf-8") as f:
                    return json.load(f)
            except (json.JSONDecodeError, IOError) as e:
                debug_log(f"Error loading shown terms: {e}, creating new record")

        return {
            "version": 1,
            "created_at": datetime.now().isoformat(),
            "shown_ids": [],
        }

    def _save_shown(self) -> None:
        """Save the shown terms record."""
        self._shown["updated_at"] = datetime.now().isoformat()
        with open(self.shown_file, "w", encoding="utf-8") as f:
            json.dump(self._shown, f, ensure_ascii=False, indent=2)

    def _build_terms_index(self) -> OrderedDict[str, dict[str, Any]]:
        """Build a flat index of all terms with unique IDs."""
        terms = OrderedDict()
        for domain, domain_terms in TERMS_GLOSSARY.items():
            for term_data in domain_terms:
                # Create unique ID from domain + term
                term_id = f"{domain}:{term_data['term'].lower().replace(' ', '_')}"
                terms[term_id] = {
                    "id": term_id,
                    "domain": domain,
                    **term_data
                }
        return terms

    def get_unshown_terms(self, count: int = 3, domain: str | None = None) -> list[dict[str, Any]]:
        """
        Get terms that haven't been shown yet.

        Args:
            count: Number of terms to return (1-5)
            domain: Optional domain filter

        Returns:
            List of term dictionaries
        """
        count = max(1, min(5, count))  # Clamp between 1-5
        shown_ids = set(self._shown.get("shown_ids", []))

        result = []
        for term_id, term_data in self._all_terms.items():
            if term_id in shown_ids:
                continue
            if domain and term_data["domain"] != domain:
                continue
            result.append(term_data)
            if len(result) >= count:
                break

        return result

    def mark_as_shown(self, term_ids: list[str]) -> None:
        """
        Mark terms as shown so they won't appear again.

        Args:
            term_ids: List of term IDs to mark as shown
        """
        current_shown = set(self._shown.get("shown_ids", []))
        current_shown.update(term_ids)
        self._shown["shown_ids"] = list(current_shown)
        self._save_shown()
        debug_log(f"Marked {len(term_ids)} terms as shown")

    def get_shown_count(self) -> int:
        """Get the number of terms that have been shown."""
        return len(self._shown.get("shown_ids", []))

    def get_total_count(self) -> int:
        """Get the total number of available terms."""
        return len(self._all_terms)

    def get_remaining_count(self) -> int:
        """Get the number of unshown terms."""
        return self.get_total_count() - self.get_shown_count()

    def reset_shown(self) -> None:
        """Reset shown terms (use with caution)."""
        self._shown = {
            "version": 1,
            "created_at": datetime.now().isoformat(),
            "shown_ids": [],
        }
        self._save_shown()
        debug_log("Terms shown history reset")

    def get_domains(self) -> list[str]:
        """Get all available domains."""
        return list(TERMS_GLOSSARY.keys())

    def get_term_by_id(self, term_id: str) -> dict[str, Any] | None:
        """Get a specific term by its ID."""
        return self._all_terms.get(term_id)

    def search_terms(self, query: str, limit: int = 5) -> list[dict[str, Any]]:
        """
        Search terms by keyword.

        Args:
            query: Search query
            limit: Maximum results to return

        Returns:
            List of matching terms
        """
        query_lower = query.lower()
        results = []

        for term_id, term_data in self._all_terms.items():
            # Search in term name and definition
            if (query_lower in term_data["term"].lower() or
                query_lower in term_data["term_cn"] or
                query_lower in term_data["definition_en"].lower() or
                query_lower in term_data["definition_cn"]):
                results.append(term_data)
                if len(results) >= limit:
                    break

        return results


def get_session_terms(
    project_directory: str,
    count: int = 3,
    domain: str | None = None,
    auto_mark: bool = True,
    lang: str = "en",
) -> list[dict[str, Any]]:
    """
    Get terms for a learning session in a single language.

    This is a convenience function that gets unshown terms,
    optionally marks them as shown, and returns them in the
    specified language format to minimize token usage.

    Args:
        project_directory: Project directory path
        count: Number of terms to get (1-5)
        domain: Optional domain filter
        auto_mark: Whether to automatically mark terms as shown
        lang: Language code ("zh" for Chinese, "en" for English)

    Returns:
        List of term dictionaries with only the requested language
    """
    manager = TermsIndexManager(project_directory)
    terms = manager.get_unshown_terms(count=count, domain=domain)

    if auto_mark and terms:
        manager.mark_as_shown([t["id"] for t in terms])

    # Convert to single-language format to save tokens
    is_chinese = lang.startswith("zh")
    result = []
    for t in terms:
        result.append({
            "id": t["id"],
            "domain": t["domain"],
            "term": t["term_cn"] if is_chinese else t["term"],
            "definition": t["definition_cn"] if is_chinese else t["definition_en"],
        })

    return result
