import glob
import pandas as pd

files = sorted(glob.glob(r'D:\260525\phase9_vibecoding\project\kb-platform\deploy\ragas\ragas_eval_results_*.csv'))
path = files[-1]
print('文件:', path)
df = pd.read_csv(path, encoding='utf-8-sig')
cols = ['faithfulness', 'answer_relevancy', 'context_precision',
        'context_recall', 'answer_correctness']
avg = df[df.iloc[:, 0].astype(str) == '平均值']
print('--- 五指标均值 ---')
if len(avg):
    for c in cols:
        if c in avg.columns:
            print(f'{c:<22}', round(float(avg.iloc[0][c]), 4))
valid = df[df.iloc[:, 0].astype(str) != '平均值']
print('样本数:', len(valid))
nan_count = {c: int(pd.to_numeric(df[c], errors='coerce').isna().sum()) for c in cols if c in df.columns}
print('NaN 分布:', nan_count)
