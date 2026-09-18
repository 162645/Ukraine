#!/usr/bin/env python3
"""Re-render all Aug26 figures with Chinese in-plot text from frozen CSVs."""
from pathlib import Path
import hashlib, json
import numpy as np, pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import Patch, Polygon
from matplotlib.collections import PatchCollection
from matplotlib.font_manager import FontProperties

ROOT=Path('/home/wsl/XiaoLunWen_doc_complete_20260908')
PKG=ROOT/'paper_final_assets_20260912_bilingual'
RUN=ROOT/'runs/aug26_state_case_study_20260912/results/stages/stage_aug26_state_case_study'
FONT='/usr/share/fonts/wqy-microhei/wqy-microhei.ttc'
FP=FontProperties(fname=FONT)
plt.rcParams['font.family'] = FP.get_name()
plt.rcParams['axes.unicode_minus'] = False
Q=[f'Q{i}' for i in range(1,6)]; D=[f'D{i}' for i in range(1,11)]
CN={'Volyn':'沃伦','Zaporizhzhia':'扎波罗热','Cherkasy':'切尔卡瑟','Kirovohrad':'基洛沃格勒','Sumy':'苏梅','Mykolaiv':'尼古拉耶夫','Lviv':'利沃夫','Poltava':'波尔塔瓦','Rivne':'罗夫诺','Odesa':'敖德萨','Zakarpattia':'外喀尔巴阡','Khmelnytskyi':'赫梅利尼茨基','Ternopil':'捷尔诺波尔','Ivano-Frankivsk':'伊万诺-弗兰科夫斯克','Zhytomyr':'日托米尔','Kyiv':'基辅','Chernihiv':'切尔尼戈夫'}
COL={'ROBUST_POSITIVE':'#1b7837','DIRECTIONAL_POSITIVE':'#78c679','DIRECTIONAL_NEGATIVE':'#6baed6','ROBUST_NEGATIVE':'#2166ac','NOT_ESTIMABLE':'#969696'}

def save(fig, stem):
    stem.parent.mkdir(parents=True,exist_ok=True)
    for ext,dpi in [('png',300),('pdf',None),('svg',None)]: fig.savefig(stem.with_suffix('.'+ext),dpi=dpi,bbox_inches='tight');
    plt.close(fig)

def state_name(s): return CN.get(str(s).replace(' Oblast',''), str(s).replace(' Oblast',''))

def main():
    out=PKG/'figures_appendix'/'zh'
    summ=pd.read_csv(RUN/'aug26_state_sensitivity_activity_summary.csv')
    q=pd.read_csv(RUN/'aug26_state_sensitivity_summary.csv')
    d=pd.read_csv(RUN/'aug26_state_activity_summary.csv')
    order=summ.sort_values('adjusted_q5_q1',ascending=False).target_admin1.tolist(); sn=summ.set_index('target_admin1').loc[order]
    # 1 forest
    fig,ax=plt.subplots(figsize=(9,7)); y=np.arange(len(sn))
    for i,(name,r) in enumerate(sn.iterrows()):
        lo,hi=r.adjusted_q5_q1_ci_low*100,r.adjusted_q5_q1_ci_high*100; x=r.adjusted_q5_q1*100
        ax.plot([lo,hi],[i,i],color=COL.get(r.sensitivity_class,'#666'),lw=2); ax.scatter(x,i,color=COL.get(r.sensitivity_class,'#666'),s=35,zorder=3)
    ax.axvline(0,color='black',lw=.9); ax.set_yticks(y,[state_name(x) for x in order]); ax.invert_yaxis(); ax.set_xlabel('正常活跃度调整后的 Q5−Q1 平均可达性下降（百分点）',fontproperties=FP); ax.set_ylabel('州（统一排序）',fontproperties=FP); ax.set_title('2024-08-26：州级计划停电敏感度效应（探索性案例）',fontproperties=FP); ax.grid(axis='x',alpha=.2)
    ax.legend(handles=[Patch(facecolor=c,label=k.replace('ROBUST_POSITIVE','稳健正向').replace('DIRECTIONAL_POSITIVE','方向正向').replace('DIRECTIONAL_NEGATIVE','方向负向').replace('ROBUST_NEGATIVE','稳健负向').replace('NOT_ESTIMABLE','不可估计')) for k,c in COL.items()],loc='lower right',frameon=False,prop=FP,fontsize=7); save(fig,out/'FIG-AUG26-1_sensitivity_forest')
    # 2 sensitivity heatmap
    piv=q.pivot(index='target_admin1',columns='quintile',values='activity_adjusted_mean_reach_drop').reindex(order); h=piv.sub(piv.Q1,axis=0)*100; lim=max(abs(np.nanmin(h)),abs(np.nanmax(h)),1)
    fig,ax=plt.subplots(figsize=(7,7)); im=ax.imshow(h,aspect='auto',cmap='RdBu_r',vmin=-lim,vmax=lim); ax.set_xticks(range(5),Q); ax.set_yticks(range(len(order)),[state_name(x) for x in order]); ax.set_xlabel('冻结的计划停电敏感度五分位组',fontproperties=FP); ax.set_ylabel('州（统一排序）',fontproperties=FP); ax.set_title('2024-08-26：州内正常活跃度调整后的计划停电敏感度梯度（探索性）',fontproperties=FP); fig.colorbar(im,ax=ax,label='相对 Q1 的差值（百分点）')
    for i in range(len(h)):
        for j in range(5):
            if np.isfinite(h.iloc[i,j]): ax.text(j,i,f'{h.iloc[i,j]:.1f}',ha='center',va='center',fontsize=7)
    fig.tight_layout(); save(fig,out/'FIG-AUG26-2_sensitivity_heatmap')
    # 3 small multiples
    raw=q.pivot_table(index='target_admin1',columns='quintile',values='raw_mean_reach_drop').reindex(order)*100; adj=piv*100
    nr=int(np.ceil(len(order)/4)); fig,axes=plt.subplots(nr,4,figsize=(13,2.6*nr),sharex=True,sharey=True); axes=np.asarray(axes).ravel()
    for i,n in enumerate(order):
        ax=axes[i]; ax.plot(range(5),raw.loc[n].to_numpy(),'--o',color='.45',ms=3,label='未调整' if i==0 else None); ax.plot(range(5),adj.loc[n].to_numpy(),'-o',color='#2166ac',ms=3,label='正常活跃度调整后' if i==0 else None); ax.set_title(f'{state_name(n)}\nN={int(sn.loc[n,"valid_ip_n_main"]):,}',fontproperties=FP,fontsize=8); ax.set_xticks(range(5),Q); ax.grid(axis='y',alpha=.2)
    for ax in axes[len(order):]: ax.axis('off')
    axes[0].set_ylabel('平均可达性下降（百分点）',fontproperties=FP); axes[0].legend(frameon=False,prop=FP,fontsize=8); fig.suptitle('2024-08-26：各州计划停电敏感度五分位曲线（探索性）',fontproperties=FP,y=.995); fig.tight_layout(); save(fig,out/'FIG-AUG26-3_state_quintile_small_multiples')
    # 4 activity forest
    fig,ax=plt.subplots(figsize=(9,7));
    for i,(name,r) in enumerate(sn.iterrows()): ax.plot([r.activity_d10_d1_ci_low*100,r.activity_d10_d1_ci_high*100],[i,i],color='#238b45',lw=2); ax.scatter(r.activity_d10_d1*100,i,color='#238b45',s=35,zorder=3)
    ax.axvline(0,color='black',lw=.9); ax.set_yticks(y,[state_name(x) for x in order]); ax.invert_yaxis(); ax.set_xlabel('正常活跃度：D10−D1 平均可达性下降（百分点）',fontproperties=FP); ax.set_ylabel('州（统一排序）',fontproperties=FP); ax.set_title('2024-08-26：州级正常活跃度效应（探索性对照）',fontproperties=FP); ax.grid(axis='x',alpha=.2); fig.tight_layout(); save(fig,out/'FIG-AUG26-4_activity_forest')
    # 5 activity heatmap
    dp=d.pivot(index='target_admin1',columns='activity_decile',values='mean_reach_drop').reindex(order); dh=dp.sub(dp.D1,axis=0)*100; lim=max(abs(np.nanmin(dh)),abs(np.nanmax(dh)),1)
    fig,ax=plt.subplots(figsize=(10,7.7)); im=ax.imshow(dh,aspect='auto',cmap='RdBu_r',vmin=-lim,vmax=lim); ax.set_xticks(range(10),D); ax.set_yticks(range(len(order)),[state_name(x) for x in order]); ax.set_xlabel('冻结的正常活跃度十分位组',fontproperties=FP); ax.set_ylabel('州（统一排序）',fontproperties=FP); ax.set_title('2024-08-26：州内正常活跃度梯度（探索性对照）',fontproperties=FP); fig.colorbar(im,ax=ax,label='相对 D1 的差值（百分点）'); fig.tight_layout(); save(fig,out/'FIG-AUG26-5_activity_heatmap')
    # 6/7 scatter
    def scatter(stem,ycol,ylabel,title,rho):
        fig,ax=plt.subplots(figsize=(7,5)); x=sn.state_shock_severity.to_numpy(float); yy=sn[ycol].to_numpy(float); ax.scatter(x,yy,color='#762a83',s=35); ok=np.isfinite(x)&np.isfinite(yy)
        if ok.sum()>=3:
            z=np.polyfit(x[ok],yy[ok],1); xx=np.linspace(x[ok].min(),x[ok].max(),100); ax.plot(xx,np.polyval(z,xx),color='#969696',lw=1,ls='--')
        for name in order: ax.annotate(state_name(name),(sn.loc[name,'state_shock_severity'],sn.loc[name,ycol]),xytext=(4,4),textcoords='offset points',fontproperties=FP,fontsize=7)
        ax.set(xlabel='州级冲击严重度：平均可达性下降',ylabel=ylabel,title=title); ax.text(.02,.97,f'Spearman ρ={rho:.3f}',transform=ax.transAxes,va='top'); ax.grid(alpha=.2); fig.tight_layout(); save(fig,out/stem)
    scatter('FIG-AUG26-6_shock_vs_sensitivity','adjusted_q5_q1','正常活跃度调整后的 Q5−Q1 可达性下降','探索性：冲击严重度与计划停电敏感度',-0.0417)
    scatter('FIG-AUG26-7_shock_vs_activity','activity_d10_d1','D10−D1 可达性下降','探索性：冲击严重度与正常活跃度',0.8706)
    # 8 quadrants
    fig,ax=plt.subplots(figsize=(7,5)); ax.axvline(0,color='.25',lw=.8); ax.axhline(0,color='.25',lw=.8); ax.scatter(sn.activity_d10_d1*100,sn.adjusted_q5_q1*100,color='#762a83',s=35)
    for name,r in sn.iterrows(): ax.annotate(state_name(name),(r.activity_d10_d1*100,r.adjusted_q5_q1*100),xytext=(4,4),textcoords='offset points',fontproperties=FP,fontsize=7)
    ax.set(xlabel='正常活跃度：D10−D1 可达性下降（百分点）',ylabel='正常活跃度调整后的计划停电敏感度：Q5−Q1 可达性下降（百分点）',title='2024-08-26：正常活跃度与计划停电敏感度四象限（探索性）'); ax.grid(alpha=.2); fig.tight_layout(); save(fig,out/'FIG-AUG26-8_activity_sensitivity_quadrants')
    # 9 map with Chinese title/legend; geometry is frozen external GeoJSON.
    geo=json.loads((ROOT/'data_external/geography/geoBoundaries-UKR-ADM1.geojson').read_text()); patches=[]; colors=[]
    for feat in geo.get('features',[]):
        name=feat.get('properties',{}).get('shapeName'); geom=feat.get('geometry',{}); coords=geom.get('coordinates',[]); polys=coords if geom.get('type')=='MultiPolygon' else [coords]
        for poly in polys:
            if poly: patches.append(Polygon(poly[0],closed=True)); colors.append(COL.get(sn.loc[name,'sensitivity_class'] if name in sn.index else 'NOT_ESTIMABLE','#eeeeee'))
    fig,ax=plt.subplots(figsize=(8,7)); ax.add_collection(PatchCollection(patches,facecolor=colors,edgecolor='white',linewidth=.4)); ax.autoscale(); ax.set_aspect('equal'); ax.set_axis_off(); ax.set_title('2024-08-26：正常活跃度调整后的计划停电敏感度分类（探索性）',fontproperties=FP); ax.text(.015,.025,'稳健正向=深绿  方向正向=浅绿  方向负向=浅蓝  稳健负向=深蓝  不可估计=灰',transform=ax.transAxes,fontproperties=FP,fontsize=7,ha='left',va='bottom',bbox=dict(facecolor='white',edgecolor='.6',alpha=.9,pad=4)); save(fig,out/'FIG-AUG26-9_sensitivity_classification_map')
    # 10 paired forest, fully Chinese.
    fig,axes=plt.subplots(1,2,figsize=(11,8.4),sharey=True,gridspec_kw={'wspace':.06})
    for ax,val,lo,hi,xlab,title in [(axes[0],'adjusted_q5_q1','adjusted_q5_q1_ci_low','adjusted_q5_q1_ci_high','正常活跃度调整后的 Q5−Q1 可达性下降（百分点）','计划停电敏感度'),(axes[1],'activity_d10_d1','activity_d10_d1_ci_low','activity_d10_d1_ci_high','D10−D1 可达性下降（百分点）','正常活跃度')]:
        xx=sn[val].to_numpy()*100; low=xx-sn[lo].to_numpy()*100; high=sn[hi].to_numpy()*100-xx; ax.errorbar(xx,y,xerr=[low,high],fmt='none',ecolor='#555',elinewidth=1,capsize=2); ax.scatter(xx,y,s=24,c=np.where(xx>=0,'#1f77b4','#d95f02'),edgecolor='white',linewidth=.3); ax.axvline(0,color='#222',lw=.9); ax.set_xlabel(xlab,fontproperties=FP); ax.set_title(title,fontproperties=FP,fontsize=10); ax.grid(axis='x',color='#ddd',lw=.6); ax.spines[['top','right']].set_visible(False)
    axes[0].set_yticks(y,[state_name(x) for x in order]); axes[0].set_ylabel('州（统一排序）',fontproperties=FP); fig.suptitle('2024-08-26 探索性州级对照：计划停电敏感度与正常活跃度',fontproperties=FP,fontsize=13); fig.text(.5,.01,'点为州级估计；误差线为 /24 前缀聚类自助法 95% 置信区间。',ha='center',fontproperties=FP,fontsize=8); fig.subplots_adjust(left=.2,right=.98,bottom=.08,top=.94); save(fig,out/'09_aug26_paired_sensitivity_activity_forest')
    print('rendered full Chinese Aug26 figures')

if __name__=='__main__': main()
