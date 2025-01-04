# NipponStudyKit 日本留学工具包

这个工具包是为了要去日本留学的孩子们写的，所谓工具包：这就是一堆小工具的集合，并不是什么大而全的东西。

我在做这个工具包的过程中，尽可能的使用包括LLM在内的各种时下流行的AI工具，是工具也是为了实践新的生产力。

## get_admissions_handbooks

这个工具用于在互联网上抓取日本各所大学的招生信息（募集要项）。

日本的网站怎么说的，一言难尽，用过去传统的蜘蛛的做法可能不是什么容易的解决方案。于是我引用了名为[browser-use](https://github.com/browser-use/browser-use)的工具新贵（已经有9K的Star了）。

通过[Open-Router](https://openrouter.ai/)调用OpenAI的[Gpt-4o-mini](https://openrouter.ai/openai/gpt-4o-mini)来帮我甄别，哪些信息是我要的招生信息。

同时为了应对[browser-use](https://github.com/browser-use/browser-use)运行起来略迟缓的问题，我做了个简单的并发处理，来提升效率。

### 工具的使用
 - 一切之前，请你准备好[Open-Router](https://openrouter.ai/)的API KEY，还要完成充值
 - 首先，你需要按照[browser-use](https://github.com/browser-use/browser-use)的方法完成browser-use的安装
 - 其次，你还需要安装一些get_admissions_handbooks引用的依赖，因为这个Kit不是给小白用的，所以如果这一步不会的就不要自己动手了
 - 将.env.sample改名为.env，并把你的API KEY更新过去
 - 将eju_accepted_u_list.csv.sample改名为任意.csv文件，并将你感兴趣的学校的信息更新上去
 - 在运行之前，你还需要打开get_admissions_handbooks.py
  - 在代码的最下面，更新你自己的csv文件的名称
  - 根据你的内存情况更新并发的数量

![示例动画](get_admissions_handbooks.gif)
