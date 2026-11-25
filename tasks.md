
# tasks
开发一个基于AI 股票信息的量化因子系统，包含：


1. 包含股票信息数据ETL，写入本地数据库duckbd or sqllite
2. 下载指定日期的财报信息，提取关键字段，营收，利润，支出
3. 可视化股票信息，支持不同公司的对比，能根据ROE, PE, 波动率，行业属性等创建股票选择池子
4. 能根据因子进行回测，过去十年的策略表现


UI 需要展示的效果，UI风格不用参考，需要统一美观 
C:\Users\HW\OneDrive\Desktop\Hang_doc\quant_data\refer_ui 

参考项目和数据源
https://github.com/ZhuLinsen/daily_stock_analysis/blob/main/docs/full-guide.md#%E6%95%B0%E6%8D%AE%E6%BA%90%E9%85%8D%E7%BD%AE

可以在github 找 量化投资邢不行啊 相关的仓库进行参考

先给我一个开发计划和outline，我确认后在开发出一个MVP版本，快速验证，然后完善整个系统
