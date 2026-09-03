"""Statistical utilities with explicit clustering and event-level resampling."""
from __future__ import annotations

import numpy as np
import pandas as pd


def block_bootstrap_mean(values, blocks, n_boot=1000, ci=0.95, seed=0):
    values = np.asarray(values, float); blocks = np.asarray(blocks)
    ok = np.isfinite(values)
    values, blocks = values[ok], blocks[ok]
    if len(values) == 0:
        return np.nan, np.nan, np.nan
    uniq = pd.unique(blocks)
    idx = {b: np.flatnonzero(blocks == b) for b in uniq}
    rng = np.random.default_rng(seed)
    boot = []
    for _ in range(n_boot):
        picks = rng.choice(uniq, len(uniq), replace=True)
        take = np.concatenate([idx[b] for b in picks])
        boot.append(np.nanmean(values[take]))
    alpha = (1-ci)/2
    return float(np.nanmean(values)), float(np.quantile(boot, alpha)), float(np.quantile(boot, 1-alpha))


def cluster_bootstrap_metric(df: pd.DataFrame, block_col: str, metric_fn, n_boot=1000, ci=0.95, seed=0):
    if df.empty:
        return np.nan, np.nan, np.nan, np.array([])
    blocks = pd.unique(df[block_col])
    observed = float(metric_fn(df))
    rng = np.random.default_rng(seed)
    vals = []
    grouped = {b: df[df[block_col].eq(b)] for b in blocks}
    for _ in range(n_boot):
        pick = rng.choice(blocks, len(blocks), replace=True)
        sample = pd.concat([grouped[b].assign(_boot_block=i) for i, b in enumerate(pick)], ignore_index=True)
        try:
            vals.append(float(metric_fn(sample)))
        except Exception:
            vals.append(np.nan)
    vals = np.asarray(vals, float)
    alpha = (1-ci)/2
    return observed, float(np.nanquantile(vals, alpha)), float(np.nanquantile(vals, 1-alpha)), vals


def bh_fdr(pvals, alpha=0.05):
    p = np.asarray(pvals, float)
    valid = np.isfinite(p)
    out = np.zeros(len(p), bool)
    if valid.sum() == 0: return out
    pv = p[valid]; order = np.argsort(pv); ranked = pv[order]
    passed = ranked <= alpha*np.arange(1,len(ranked)+1)/len(ranked)
    if passed.any():
        k = np.flatnonzero(passed).max()+1
        valid_idx = np.flatnonzero(valid)
        out[valid_idx[order[:k]]] = True
    return out


def km_survival(durations, events):
    durations=np.asarray(durations,float); events=np.asarray(events,int)
    ok=np.isfinite(durations); durations,events=durations[ok],events[ok]
    if len(durations)==0: return np.array([]),np.array([])
    order=np.argsort(durations); durations,events=durations[order],events[order]
    at_risk=len(durations); s=1.0; times=[0.0]; surv=[1.0]
    for t in np.unique(durations):
        d=int(np.sum((durations==t)&(events==1))); c=int(np.sum((durations==t)&(events==0)))
        if at_risk and d: s*=1-d/at_risk
        times.append(float(t)); surv.append(float(s)); at_risk-=d+c
    return np.asarray(times),np.asarray(surv)


def spearman(a,b):
    from scipy.stats import spearmanr
    a=np.asarray(a,float);b=np.asarray(b,float);ok=np.isfinite(a)&np.isfinite(b)
    return float(spearmanr(a[ok],b[ok]).correlation) if ok.sum()>=3 else np.nan


def jensen_shannon(p: dict, q: dict) -> float:
    keys=sorted(set(p)|set(q))
    if not keys:return 0.0
    pv=np.array([p.get(k,0) for k in keys],float);qv=np.array([q.get(k,0) for k in keys],float)
    if pv.sum()==0 or qv.sum()==0:return np.nan
    pv/=pv.sum();qv/=qv.sum();m=.5*(pv+qv)
    def kl(x,y):
        z=x>0;return float(np.sum(x[z]*np.log2(x[z]/y[z])))
    return .5*kl(pv,m)+.5*kl(qv,m)


def jsd_multinomial_test(base: dict, event: dict, n_perm=200, seed=0):
    obs=jensen_shannon(base,event)
    keys=sorted(set(base)|set(event))
    if not keys or not np.isfinite(obs):return obs,np.nan,np.nan
    b=np.array([base.get(k,0) for k in keys],int);e=np.array([event.get(k,0) for k in keys],int)
    nb,ne=b.sum(),e.sum();pooled=(b+e)/(nb+ne)
    rng=np.random.default_rng(seed);null=[]
    for _ in range(n_perm):
        bb=rng.multinomial(nb,pooled);ee=rng.multinomial(ne,pooled)
        null.append(jensen_shannon(dict(zip(keys,bb)),dict(zip(keys,ee))))
    null=np.asarray(null,float)
    return obs,float((np.sum(null>=obs)+1)/(len(null)+1)),float(np.nanmedian(null))


def shannon_entropy(freqs: dict) -> float:
    x=np.asarray(list(freqs.values()),float)
    if x.sum()<=0:return np.nan
    p=x/x.sum();p=p[p>0]
    return float(-np.sum(p*np.log(p)))
