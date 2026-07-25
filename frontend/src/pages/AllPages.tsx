import { useCallback, useEffect, useMemo, useState } from 'react';
import {
  AlertTriangle, CheckCircle, ChevronDown, ChevronRight, Clock,
  Edit3, Eye, FileText, FolderTree, Layers, Play, Plus, RefreshCw, Save,
  Search, SkipForward, Tag, Trash2, XCircle,
} from 'lucide-react';
import { apiClient } from '../lib/api';
import type { Content, Creator, Note, PendingClaim, ProcessStats, Settings as SettingsType, Task } from '../lib/types';

/* ─── shared ─── */
function Spinner({ label = '加载中...' }: { label?: string }) {
  return <div className="flex items-center gap-2 text-slate-400 text-sm py-4"><RefreshCw className="animate-spin" size={16} /><span>{label}</span></div>;
}
function ErrorBox({ message }: { message: string }) {
  return <div className="card border-red-900 text-red-300 text-sm"><div className="flex items-center gap-2"><AlertTriangle size={16} /><span>{message}</span></div></div>;
}
function StatusBadge({ status }: { status: string }) {
  const map: Record<string,string> = {
    done:'badge-green',completed:'badge-green',confirmed:'badge-green',reviewed:'badge-green',
    failed:'badge-red',error:'badge-red',removed:'badge-red',
    pending:'badge-yellow',fetching:'badge-blue',transcribing:'badge-blue',
    cleaning:'badge-blue',classifying:'badge-blue',extracting:'badge-blue',processing:'badge-blue',
  };
  return <span className={`badge ${map[(status||'').toLowerCase()]||'badge-gray'}`}>{status||'-'}</span>;
}
function fmtDur(s?: number) { if(!s||s<=0) return '-'; const m=Math.floor(s/60),x=Math.floor(s%60); return `${m}:${x.toString().padStart(2,'0')}`; }
function safeDate(v?: string) { if(!v) return '-'; const d=new Date(v); return isNaN(d.getTime())?v:d.toLocaleString('zh-CN',{hour12:false}); }

function useAsync<T>(fetcher:()=>Promise<T>,deps:unknown[]=[]) {
  const cb=useCallback(fetcher,deps);
  const [data,setData]=useState<T|null>(null);
  const [loading,setLoading]=useState(true);
  const [error,setError]=useState('');
  const run=useCallback(()=>{ let a=true; setLoading(true); setError('');
    cb().then(d=>{if(a){setData(d);setLoading(false);}})
      .catch(e=>{if(a){setError(e instanceof Error?e.message:String(e));setLoading(false);}});
    return()=>{a=false;}; },[cb]);
  useEffect(()=>run(),[run]);
  return { data, loading, error, reload:run };
}

/* ─── 1. Dashboard ─── */
export function Dashboard() {
  const stats = useAsync<ProcessStats>(()=>apiClient.get('/api/process/stats'));
  const creators = useAsync<Creator[]>(()=>apiClient.get('/api/creators'));
  const s=stats.data; const recent=(creators.data||[]).slice(0,6);
  const cards:{label:string;value:number;color:string}[] = s ? [
    {label:'创作号',value:creators.data?.length||0,color:'text-blue-400'},
    {label:'内容总数',value:s.total,color:'text-white'},
    {label:'已完成',value:s.done,color:'text-green-400'},
    {label:'失败',value:s.failed,color:'text-red-400'},
    {label:'待处理',value:s.pending,color:'text-yellow-400'},
  ] : [];
  if (stats.loading||creators.loading) return <Spinner/>;
  if (stats.error) return <ErrorBox message={stats.error}/>;
  return (
    <div className="space-y-6">
      <div className="grid grid-cols-2 md:grid-cols-5 gap-4">
        {cards.map(c=>(
          <div key={c.label} className="card"><div className="text-xs text-slate-400">{c.label}</div><div className={`text-2xl font-bold mt-1 ${c.color}`}>{c.value}</div></div>
        ))}
      </div>
      <div className="card">
        <h3 className="font-semibold text-white mb-3">最近创作号</h3>
        {recent.length===0 ? <p className="text-sm text-slate-500">暂无</p> : (
          <ul className="space-y-2">{recent.map(c=>(
            <li key={c.id} className="flex items-center justify-between text-sm">
              <span className="text-white">{c.name}</span><span className="text-xs text-slate-500">{c.platform} · {safeDate(c.last_checked)}</span>
            </li>))}</ul>
        )}
      </div>
    </div>
  );
}

/* ─── Batch BV Input ─── */
function BatchBvidInput({ onDone }: { onDone: () => void }) {
  const [text, setText] = useState('');
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState('');
  const submit = async () => {
    if (!text.trim()) return;
    setBusy(true); setResult('');
    try {
      const r = await apiClient.post<any>('/api/process/bvid-batch', { bvids: text });
      setResult(`完成: ${r.success}/${r.total} 成功`);
      setText('');
      onDone();
    } catch (e) { setResult(`失败: ${e instanceof Error ? e.message : String(e)}`); }
    finally { setBusy(false); }
  };
  return (
    <div className="mt-2">
      <textarea className="w-full text-sm" rows={5} placeholder="BV1xxx&#10;BV2yyy&#10;BV3zzz" value={text} onChange={e=>setText(e.target.value)} />
      <div className="flex items-center gap-2 mt-1">
        <button className="btn btn-primary text-xs" disabled={busy||!text.trim()} onClick={submit}>
          {busy ? <RefreshCw size={12} className="animate-spin"/> : <Play size={12}/>} 批量处理
        </button>
        {result && <span className="text-xs text-slate-400">{result}</span>}
      </div>
    </div>
  );
}

/* ─── 2. Creators (合并内容清单) ─── */
const UPDATE_STRATEGIES = [
  { value: 'select', label: '选择更新' },
  { value: 'auto', label: '全选更新' },
  { value: 'paused', label: '暂停' },
];
const PRIORITIES = [
  { value: 'realtime', label: '实时' },
  { value: 'normal', label: '常规' },
  { value: 'low', label: '低频' },
];
const CONTENT_TYPES = ['教程类','指导类','导购类','资讯类','娱乐类','访谈类','评论类'];

export function Creators() {
  const { data, loading, error, reload } = useAsync<Creator[]>(()=>apiClient.get('/api/creators'));
  const [biliSearch,setBiliSearch]=useState(''); const [wcSearch,setWcSearch]=useState('');
  const [addBili,setAddBili]=useState({uid:'',name:'',update_strategy:'select',priority:'normal',content_types:[] as string[]});
  const [addWc,setAddWc]=useState({uid:'',name:'',update_strategy:'select',priority:'normal',content_types:[] as string[]});
  const [busy,setBusy]=useState(false); const [notice,setNotice]=useState('');
  const [expandedId,setExpandedId]=useState<number|null>(null);
  const [bvidInput,setBvidInput]=useState(''); const [bvidBusy,setBvidBusy]=useState(false);
  const creators=data||[];
  const bili=creators.filter(c=>c.platform==='bilibili'&&(c.name?.toLowerCase().includes(biliSearch.toLowerCase())||c.uid?.includes(biliSearch)));
  const wc=creators.filter(c=>c.platform==='wechat'&&(c.name?.toLowerCase().includes(wcSearch.toLowerCase())||c.uid?.includes(wcSearch)));

  const add=async(platform:string,form:any)=>{
    if(!form.uid.trim())return; setBusy(true); setNotice('');
    try{ await apiClient.post('/api/creators',{platform,uid:form.uid.trim(),name:form.name.trim(),update_strategy:form.update_strategy,priority:form.priority,content_types:form.content_types});
      setNotice('添加成功'); reload();
      if(platform==='bilibili') setAddBili({uid:'',name:'',update_strategy:'select',priority:'normal',content_types:[]});
      else setAddWc({uid:'',name:'',update_strategy:'select',priority:'normal',content_types:[]});
    }catch(e){setNotice(`失败: ${e instanceof Error?e.message:String(e)}`);}finally{setBusy(false);}
  };
  const del=async(id:number,name:string)=>{
    if(!confirm(`删除「${name}」？关联内容也会删除。`))return; setBusy(true);
    try{await apiClient.del(`/api/creators/${id}`);setNotice('已删除');reload();}catch(e){setNotice(`失败: ${e}`);}finally{setBusy(false);}
  };
  const check=async(c:Creator)=>{
    setBusy(true); setNotice('');
    try{const r=await apiClient.get<any>(`/api/creators/${c.id}/check`);setNotice(`检查完成: ${r.new_count} 个新视频`);reload();}catch(e){setNotice(`失败: ${e}`);}finally{setBusy(false);}
  };
  const updateCreator=async(id:number,field:string,value:any)=>{
    try{await apiClient.put(`/api/creators/${id}`,{[field]:value});reload();}catch(e){setNotice(`失败: ${e}`);}
  };
  const processBvid=async()=>{
    const bvid=bvidInput.trim(); if(!bvid)return; setBvidBusy(true); setNotice('');
    try{const r=await apiClient.post<any>(`/api/process/bvid/${bvid}`);setNotice(r.success?`处理成功: ${r.title||bvid}`:`失败: ${r.error||''}`);setBvidInput('');reload();}catch(e){setNotice(`失败: ${e}`);}finally{setBvidBusy(false);}
  };

  if(loading) return <Spinner/>;
  if(error) return <ErrorBox message={error}/>;

  // 添加表单（含标签选择）
  const AddForm=({platform,form,setForm}:{platform:string;form:any;setForm:(v:any)=>void})=>(
    <div className="border border-slate-800 rounded-lg p-3 mb-3 bg-slate-900/40">
      <div className="flex gap-2 mb-2">
        <input className="flex-1" placeholder="UID" value={form.uid} onChange={e=>setForm({...form,uid:e.target.value})}/>
        <input className="flex-1" placeholder="名称(可选)" value={form.name} onChange={e=>setForm({...form,name:e.target.value})}/>
        <button className="btn btn-primary text-xs whitespace-nowrap" disabled={busy||!form.uid.trim()} onClick={()=>add(platform,form)}>
          <Plus size={14}/> 添加
        </button>
      </div>
      <div className="flex flex-wrap gap-2 text-xs">
        <select className="text-xs" value={form.update_strategy} onChange={e=>setForm({...form,update_strategy:e.target.value})}>
          {UPDATE_STRATEGIES.map(s=><option key={s.value} value={s.value}>{s.label}</option>)}
        </select>
        <select className="text-xs" value={form.priority} onChange={e=>setForm({...form,priority:e.target.value})}>
          {PRIORITIES.map(p=><option key={p.value} value={p.value}>{p.label}</option>)}
        </select>
        <div className="flex items-center gap-1 flex-wrap">
          {CONTENT_TYPES.map(t=>(
            <button key={t} type="button"
              className={`badge text-xs cursor-pointer ${form.content_types.includes(t)?'badge-blue':'badge-gray'}`}
              onClick={()=>{const has=form.content_types.includes(t);
                setForm({...form,content_types:has?form.content_types.filter((x:string)=>x!==t):[...form.content_types,t]})}}>
              {t}
            </button>
          ))}
        </div>
      </div>
    </div>
  );

  // 创作号卡片（含可折叠视频列表）
  const CreatorCard=({c}:{c:Creator})=>{
    const expanded=expandedId===c.id;
    const [videos,setVideos]=useState<any[]>([]);
    const [vidLoading,setVidLoading]=useState(false);
    const [selectedIds,setSelectedIds]=useState<Set<number>>(new Set());
    const [batchBusy,setBatchBusy]=useState(false);
    const [rowBusyId,setRowBusyId]=useState<number|null>(null);
    const [catForBatch,setCatForBatch]=useState<string>(CONTENT_TYPES[0]);

    const toggle=async()=>{
      if(expanded){setExpandedId(null);return;}
      setExpandedId(c.id);
      if(c.platform==='bilibili'){
        setVidLoading(true);
        try{
          const r=await apiClient.get<any>(`/api/creators/${c.id}/check`);
          setVideos(r.new_videos||[]);
        }catch(e){setVideos([]);}
        setVidLoading(false);
      }
    };
    const toggleSel=(id:number)=>{
      setSelectedIds(prev=>{const n=new Set(prev);n.has(id)?n.delete(id):n.add(id);return n;});
    };
    const allSelected=videos.length>0 && videos.every((v:any)=>selectedIds.has(v.content_id));
    const selectAll=()=>setSelectedIds(allSelected?new Set():new Set(videos.map((v:any)=>v.content_id).filter(Boolean)));

    // 通用批量操作：调用 /contents/batch-operations
    const runBatch=async(action:'reprocess'|'skip'|'delete'|'change_category',extra?:{category?:string})=>{
      const ids=Array.from(selectedIds);
      if(ids.length===0)return;
      setBatchBusy(true); setNotice('');
      try{
        const body:any={action,ids};
        if(action==='change_category'&&extra?.category)body.category=extra.category;
        await apiClient.post('/api/contents/batch-operations',body);
        const lbl={reprocess:'批量处理',skip:'跳过',delete:'删除',change_category:'改分类'}[action];
        setNotice(`${lbl} ${ids.length} 项完成`);
        setSelectedIds(new Set());
        if(action!=='skip'&&action!=='change_category'){
          // 需要重新拉取视频列表
          const r=await apiClient.get<any>(`/api/creators/${c.id}/check`);
          setVideos(r.new_videos||[]);
        }
        reload();
      }catch(e){setNotice(`批量${action}失败: ${e instanceof Error?e.message:String(e)}`);}
      setBatchBusy(false);
    };

    // 单行操作
    const rowBatch=async(id:number,action:'skip'|'delete')=>{
      if(!id)return;
      if(action==='delete'&&!confirm('删除此内容？关联笔记也会删除。'))return;
      setRowBusyId(id); setNotice('');
      try{
        await apiClient.post('/api/contents/batch-operations',{action,ids:[id]});
        setNotice(action==='delete'?'已删除':'已跳过');
        // 从本地列表移除
        setVideos(prev=>prev.filter((v:any)=>v.content_id!==id));
        setSelectedIds(prev=>{const n=new Set(prev);n.delete(id);return n;});
        reload();
      }catch(e){setNotice(`操作失败: ${e instanceof Error?e.message:String(e)}`);}
      setRowBusyId(null);
    };

    return (
      <div className="rounded-lg border border-slate-800 p-3 bg-slate-900/60">
        <div className="flex items-start justify-between gap-2">
          <div className="min-w-0 flex-1 cursor-pointer" onClick={toggle}>
            <div className="flex items-center gap-2">
              {expanded ? <ChevronDown size={14} className="text-slate-400"/> : <ChevronRight size={14} className="text-slate-400"/>}
              <span className="text-white font-medium">{c.name}</span>
              <span className="text-xs text-slate-500">{c.uid}</span>
            </div>
            <div className="flex flex-wrap items-center gap-1.5 mt-1.5 ml-5">
              <select className="badge badge-blue text-xs cursor-pointer border-0" value={c.update_strategy}
                onChange={e=>updateCreator(c.id,'update_strategy',e.target.value)}
                onClick={e=>e.stopPropagation()}>
                {UPDATE_STRATEGIES.map(s=><option key={s.value} value={s.value}>{s.label}</option>)}
              </select>
              <select className="badge badge-yellow text-xs cursor-pointer border-0" value={c.priority}
                onChange={e=>updateCreator(c.id,'priority',e.target.value)}
                onClick={e=>e.stopPropagation()}>
                {PRIORITIES.map(p=><option key={p.value} value={p.value}>{p.label}</option>)}
              </select>
              {c.content_types?.map((t:string)=><span key={t} className="badge badge-gray text-xs">{t}</span>)}
            </div>
            <div className="text-xs text-slate-500 mt-1 ml-5">最后检查: {safeDate(c.last_checked)}</div>
          </div>
          <div className="flex flex-col gap-1 shrink-0">
            {c.platform==='bilibili' && <button className="btn btn-ghost text-xs px-2 py-1" disabled={busy} onClick={()=>check(c)} title="检查新视频"><RefreshCw size={12}/></button>}
            <button className="btn btn-danger text-xs px-2 py-1" disabled={busy} onClick={()=>del(c.id,c.name)} title="删除"><Trash2 size={12}/></button>
          </div>
        </div>
        {/* 折叠展开的视频列表 */}
        {expanded && c.platform==='bilibili' && (
          <div className="mt-3 pt-3 border-t border-slate-800">
            <div className="flex items-center justify-between mb-2">
              <div className="flex items-center gap-2">
                <span className="text-xs text-slate-400">视频列表 ({videos.length})</span>
                {videos.length>0 && (
                  <label className="flex items-center gap-1 text-xs text-slate-500 cursor-pointer">
                    <input type="checkbox" checked={allSelected} onChange={selectAll}/> 全选
                  </label>
                )}
              </div>
              <span className="text-xs text-slate-500">{selectedIds.size>0?`已选 ${selectedIds.size}`:''}</span>
            </div>

            {/* 批量操作栏 */}
            {selectedIds.size>0 && (
              <div className="flex flex-wrap items-center gap-2 mb-2 p-2 rounded bg-slate-800/40 border border-slate-700/50">
                <span className="text-xs text-slate-400 mr-1">批量:</span>
                <button className="btn btn-primary text-xs px-2 py-1" disabled={batchBusy} onClick={()=>runBatch('reprocess')}>
                  {batchBusy?<RefreshCw size={12} className="animate-spin"/>:<Play size={12}/>} 批量处理
                </button>
                <button className="btn btn-ghost text-xs px-2 py-1" disabled={batchBusy} onClick={()=>runBatch('skip')}>
                  <SkipForward size={12}/> 跳过
                </button>
                <button className="btn btn-danger text-xs px-2 py-1" disabled={batchBusy} onClick={()=>{ if(confirm(`删除 ${selectedIds.size} 项？`))runBatch('delete'); }}>
                  <Trash2 size={12}/> 删除
                </button>
                <div className="flex items-center gap-1">
                  <Tag size={12} className="text-slate-500"/>
                  <select className="text-xs bg-slate-900 border border-slate-700 rounded px-1 py-0.5" value={catForBatch} onChange={e=>setCatForBatch(e.target.value)} onClick={e=>e.stopPropagation()}>
                    {CONTENT_TYPES.map(t=><option key={t} value={t}>{t}</option>)}
                  </select>
                  <button className="btn btn-ghost text-xs px-2 py-1" disabled={batchBusy} onClick={()=>runBatch('change_category',{category:catForBatch})}>
                    改分类
                  </button>
                </div>
              </div>
            )}

            {vidLoading ? <Spinner label="加载视频..."/> : videos.length===0 ? (
              <p className="text-xs text-slate-500 text-center py-3">暂无新视频，点击刷新检查</p>
            ) : (
              <div className="space-y-1 max-h-80 overflow-y-auto">
                {videos.map((v:any)=>{
                  const cid:number=v.content_id;
                  const sel=selectedIds.has(cid);
                  return (
                  <div key={v.bvid||cid} className={`flex items-center gap-2 p-1.5 rounded hover:bg-slate-800/50 ${sel?'bg-slate-800/40':''}`}>
                    <input type="checkbox" checked={sel} onChange={()=>toggleSel(cid)}/>
                    <span className="text-sm text-slate-300 truncate flex-1" title={v.title}>{v.title||v.bvid}</span>
                    <span className="text-xs text-slate-500">{v.bvid}</span>
                    {/* 单行操作 */}
                    <div className="flex items-center gap-0.5 shrink-0">
                      <button className="btn btn-ghost text-xs px-1.5 py-0.5" title="跳过"
                        disabled={rowBusyId===cid||batchBusy} onClick={()=>rowBatch(cid,'skip')}>
                        <SkipForward size={11}/>
                      </button>
                      <button className="btn btn-danger text-xs px-1.5 py-0.5" title="删除"
                        disabled={rowBusyId===cid||batchBusy} onClick={()=>rowBatch(cid,'delete')}>
                        {rowBusyId===cid?<RefreshCw size={11} className="animate-spin"/>:<Trash2 size={11}/>}
                      </button>
                    </div>
                  </div>
                  );
                })}
              </div>
            )}
          </div>
        )}
      </div>
    );
  };

  const Col=({title,list,search,setSearch,addForm,setAddForm,platform}:{title:string;list:Creator[];search:string;setSearch:(v:string)=>void;addForm:any;setAddForm:(v:any)=>void;platform:string})=>(
    <div className="card flex flex-col">
      <h3 className="font-semibold text-white mb-3">{title}</h3>
      <div className="relative mb-3">
        <Search size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-slate-500"/>
        <input className="w-full pl-8" placeholder={`搜索 ${title}...`} value={search} onChange={e=>setSearch(e.target.value)}/>
      </div>
      <AddForm platform={platform} form={addForm} setForm={setAddForm}/>
      <div className="space-y-2 overflow-y-auto max-h-[65vh]">
        {list.length===0 ? <p className="text-sm text-slate-500 py-4 text-center">暂无创作号</p> :
          list.map(c=><CreatorCard key={c.id} c={c}/>)
        }
      </div>
    </div>
  );

  return (
    <div className="space-y-4">
      {notice && <div className="card text-sm text-slate-300">{notice}</div>}
      {/* BV号直接处理 + 批量 */}
      <div className="card">
        <div className="flex items-center gap-2 mb-2">
          <input className="flex-1 max-w-xs" placeholder="单个BV号" value={bvidInput}
            onChange={e=>setBvidInput(e.target.value)} onKeyDown={e=>{if(e.key==='Enter')processBvid()}}/>
          <button className="btn btn-primary text-xs whitespace-nowrap" disabled={bvidBusy||!bvidInput.trim()} onClick={processBvid}>
            {bvidBusy?<RefreshCw size={14} className="animate-spin"/>:<Play size={14}/>} 处理
          </button>
        </div>
        <details className="mt-2">
          <summary className="text-xs text-slate-400 cursor-pointer hover:text-slate-300">批量添加BV号（一行一个）</summary>
          <BatchBvidInput onDone={()=>{reload();}}/>
        </details>
      </div>
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        <Col title="B站 bilibili" list={bili} search={biliSearch} setSearch={setBiliSearch} addForm={addBili} setAddForm={setAddBili} platform="bilibili"/>
        <Col title="公众号 WeChat" list={wc} search={wcSearch} setSearch={setWcSearch} addForm={addWc} setAddForm={setAddWc} platform="wechat"/>
      </div>
    </div>
  );
}

/* ─── 3. Processing ─── */
export function Processing() {
  const stats=useAsync<any>(()=>apiClient.get('/api/process/stats'));
  const tasks=useAsync<Task[]>(()=>apiClient.get('/api/process/queue'));
  const [retryId,setRetryId]=useState<number|null>(null);
  const [notice,setNotice]=useState('');
  const [drawerId,setDrawerId]=useState<number|null>(null);
  const [drawerData,setDrawerData]=useState<any>(null);
  const [drawerLoading,setDrawerLoading]=useState(false);
  const [approveBusy,setApproveBusy]=useState(false);
  const [summaryDraft,setSummaryDraft]=useState('');
  const [summarySaving,setSummarySaving]=useState(false);
  const [batchCat,setBatchCat]=useState<string>(CONTENT_TYPES[0]);
  const s=stats.data; const taskList=tasks.data||[];

  // Keep summaryDraft in sync with drawer data when it loads/changes.
  useEffect(()=>{ setSummaryDraft(drawerData?.ai_summary||''); }, [drawerData?.ai_summary]);

  const saveSummary=async(cid:number)=>{
    setSummarySaving(true); setNotice('');
    try{ await apiClient.put(`/api/contents/${cid}/summary`,{summary:summaryDraft});
      setNotice('AI摘要已保存'); setDrawerData((d:any)=>d?{...d,ai_summary:summaryDraft}:d);
    }catch(e){ setNotice(`保存失败: ${e instanceof Error?e.message:String(e)}`); }
    setSummarySaving(false);
  };

  const cards:{label:string;value:number;color:string}[] = s ? [
    {label:'总数',value:s.total,color:'text-white'},
    {label:'待处理',value:s.pending,color:'text-yellow-400'},
    {label:'完成',value:s.done,color:'text-green-400'},
    {label:'失败',value:s.failed,color:'text-red-400'},
    ...(s.reviewing ? [{label:'待审核',value:s.reviewing,color:'text-blue-400'}] : []),
    ...(s.done_24h !== undefined ? [{label:'24h完成',value:s.done_24h,color:'text-green-300'}] : []),
  ] : [];

  const openDrawer=async(cid:number)=>{
    setDrawerId(cid); setDrawerLoading(true);
    try{ const d=await apiClient.get<any>(`/api/process/detail/${cid}`); setDrawerData(d); }
    catch(e){ setDrawerData(null); }
    setDrawerLoading(false);
  };
  const retry=async(id:number)=>{setRetryId(id);setNotice('');try{await apiClient.post(`/api/process/retry/${id}`);setNotice('已重试');stats.reload();tasks.reload();}catch(e){setNotice(`失败: ${e}`);}finally{setRetryId(null);}};
  const delTask=async(id:number)=>{if(!confirm('删除此任务？'))return;try{await apiClient.del(`/api/process/queue/${id}`);tasks.reload();}catch(e){setNotice(`失败: ${e}`);}};
  const skipContent=async(cid:number)=>{try{await apiClient.post(`/api/process/skip/${cid}`);setNotice('已跳过');stats.reload();tasks.reload();setDrawerId(null);}catch(e){setNotice(`失败: ${e}`);}};
  const approveContent=async(cid:number)=>{
    setApproveBusy(true); setNotice('');
    try{ const r=await apiClient.post<any>(`/api/process/approve/${cid}`); setNotice(`已确认: ${r.note_path||''}`); stats.reload(); tasks.reload(); setDrawerId(null); }
    catch(e){ setNotice(`失败: ${e instanceof Error?e.message:String(e)}`); }
    setApproveBusy(false);
  };

  return (
    <div className="space-y-4">
      {notice && <div className="card text-sm text-slate-300">{notice}</div>}
      <div className="grid grid-cols-2 md:grid-cols-4 lg:grid-cols-6 gap-3">
        {cards.map(c=><div key={c.label} className="card text-center"><div className="text-xs text-slate-400 mb-1">{c.label}</div><div className={`text-2xl font-bold ${c.color}`}>{c.value}</div></div>)}
      </div>
      <div className="card">
        <div className="flex items-center justify-between mb-4">
          <h3 className="font-semibold text-white">任务队列</h3>
          <button className="btn btn-ghost text-xs" onClick={tasks.reload}><RefreshCw size={14}/> 刷新</button>
        </div>
        {taskList.length===0 ? <p className="text-sm text-slate-500 text-center py-4">队列为空</p> : (
          <div className="overflow-x-auto"><table className="w-full text-sm">
            <thead><tr className="text-left text-slate-400 border-b border-slate-800">
              <th className="py-2 pr-3">ID</th><th className="py-2 pr-3">类型</th><th className="py-2 pr-3">状态</th><th className="py-2 pr-3">错误</th><th className="py-2 pr-3">操作</th>
            </tr></thead>
            <tbody>{taskList.map((t,i)=>(
              <tr key={t.id??i} className="border-b border-slate-800/60 hover:bg-slate-800/30 cursor-pointer"
                onClick={()=>openDrawer(t.content_id)}>
                <td className="py-2 pr-3">#{t.content_id}</td>
                <td className="py-2 pr-3 text-slate-300">{t.task_type}</td>
                <td className="py-2 pr-3"><StatusBadge status={t.status}/></td>
                <td className="py-2 pr-3 text-red-400 text-xs max-w-xs truncate" title={t.error}>{t.error||'-'}</td>
                <td className="py-2 pr-3"><div className="flex items-center gap-1" onClick={e=>e.stopPropagation()}>
                  {t.status==='failed' && <button className="btn btn-primary text-xs px-2 py-1" disabled={retryId===t.content_id} onClick={()=>retry(t.content_id)}><RefreshCw size={12}/> 重试</button>}
                  <button className="btn btn-ghost text-xs px-2 py-1" onClick={()=>openDrawer(t.content_id)}><Eye size={12}/></button>
                  {t.id && <button className="btn btn-danger text-xs px-2 py-1" onClick={()=>delTask(t.id!)}><Trash2 size={12}/></button>}
                </div></td>
              </tr>
            ))}</tbody>
          </table></div>
        )}
      </div>

      {/* Detail Drawer */}
      {drawerId !== null && (
        <div className="fixed inset-0 z-50 flex justify-end" onClick={()=>setDrawerId(null)}>
          <div className="absolute inset-0 bg-black/50" />
          <div className="relative w-full max-w-lg bg-slate-900 border-l border-slate-700 overflow-y-auto p-6" onClick={e=>e.stopPropagation()}>
            <div className="flex items-center justify-between mb-4">
              <h3 className="font-semibold text-white">处理详情 #{drawerId}</h3>
              <button className="btn btn-ghost text-xs" onClick={()=>setDrawerId(null)}>✕</button>
            </div>
            {drawerLoading ? <Spinner/> : drawerData ? (
              <div className="space-y-4 text-sm">
                <div>
                  <div className="text-xs text-slate-400 mb-1">标题</div>
                  <div className="text-white">{drawerData.title||'-'}</div>
                </div>
                <div>
                  <div className="text-xs text-slate-400 mb-1">状态</div>
                  <StatusBadge status={drawerData.status}/>
                </div>
                {drawerData.category && <div><div className="text-xs text-slate-400 mb-1">分类</div><div className="text-slate-300">{drawerData.category}{drawerData.sub_category?` / ${drawerData.sub_category}`:''}</div></div>}
                {drawerData.cleaned_text && (
                  <div>
                    <div className="text-xs text-slate-400 mb-1">去广告后文稿</div>
                    <div className="card text-xs text-slate-300 max-h-40 overflow-y-auto whitespace-pre-wrap">{(drawerData.cleaned_text||'').slice(0,500)}...</div>
                  </div>
                )}
                {drawerData.original_subtitle && (
                  <div>
                    <div className="text-xs text-slate-400 mb-1">原始字幕</div>
                    <div className="card text-xs text-slate-400 max-h-32 overflow-y-auto whitespace-pre-wrap">{(drawerData.original_subtitle||'').slice(0,500)}...</div>
                  </div>
                )}
                {(drawerData.ai_summary || drawerData.status==='reviewing') && (
                  <div>
                    <div className="flex items-center justify-between mb-1">
                      <span className="text-xs text-slate-400">AI摘要</span>
                      {drawerData.status==='reviewing' && (
                        <span className="text-xs text-slate-500 flex items-center gap-1"><Edit3 size={10}/> 可编辑</span>
                      )}
                    </div>
                    {drawerData.status==='reviewing' ? (
                      <>
                        <textarea className="w-full text-xs text-slate-200 bg-slate-950/60 border border-slate-700 rounded p-2"
                          rows={8} value={summaryDraft}
                          onChange={e=>setSummaryDraft(e.target.value)}
                          placeholder="编辑AI摘要后保存，再确认写入Obsidian"/>
                        <div className="flex items-center gap-2 mt-2">
                          <button className="btn btn-primary text-xs" disabled={summarySaving} onClick={()=>saveSummary(drawerId)}>
                            {summarySaving?<RefreshCw size={12} className="animate-spin"/>:<Save size={12}/>} 保存摘要
                          </button>
                          <button className="btn btn-ghost text-xs" onClick={()=>setSummaryDraft(drawerData.ai_summary||'')}>重置</button>
                        </div>
                      </>
                    ) : (
                      <div className="card text-xs text-slate-200 max-h-60 overflow-y-auto whitespace-pre-wrap">{drawerData.ai_summary}</div>
                    )}
                  </div>
                )}
                {drawerData.structured_info && (
                  <div>
                    <div className="text-xs text-slate-400 mb-1">结构化信息</div>
                    <div className="card text-xs text-slate-300 max-h-40 overflow-y-auto whitespace-pre-wrap">{drawerData.structured_info}</div>
                  </div>
                )}
                {drawerData.frame_decision && (
                  <div>
                    <div className="text-xs text-slate-400 mb-1">帧决策</div>
                    <div className="card text-xs text-slate-400">{typeof drawerData.frame_decision==='string'?drawerData.frame_decision:JSON.stringify(drawerData.frame_decision,null,2)}</div>
                  </div>
                )}
                {drawerData.error_msg && <div className="text-red-400 text-xs">错误: {drawerData.error_msg}</div>}

                {/* Action buttons */}
                <div className="flex flex-wrap gap-2 pt-4 border-t border-slate-800">
                  {drawerData.status==='reviewing' && (
                    <button className="btn btn-success text-xs" disabled={approveBusy} onClick={()=>approveContent(drawerId)}>
                      <CheckCircle size={12}/> 确认并写入Obsidian
                    </button>
                  )}
                  {(drawerData.status==='pending'||drawerData.status==='failed') && (
                    <button className="btn btn-primary text-xs" onClick={()=>{retry(drawerId);setDrawerId(null);}}>
                      <RefreshCw size={12}/> 重新处理
                    </button>
                  )}
                  {drawerData.status!=='done' && drawerData.status!=='skipped' && (
                    <button className="btn btn-ghost text-xs" onClick={()=>skipContent(drawerId)}>
                      跳过
                    </button>
                  )}
                  {drawerData.status==='done' && drawerData.note_path && (
                    <div className="text-xs text-green-400">已写入: {drawerData.note_path}</div>
                  )}
                </div>
              </div>
            ) : <ErrorBox message="无法获取详情"/>}
          </div>
        </div>
      )}
    </div>
  );
}

/* ─── 4. Notes ─── */
export function Notes() {
  const { data, loading, error, reload } = useAsync<{notes:Note[],count:number}>(()=>apiClient.get('/api/notes'));
  const [query,setQuery]=useState(''); const [busy,setBusy]=useState(false); const [notice,setNotice]=useState('');
  const allNotes=data?.notes||[];
  const grouped=useMemo(()=>{
    const q=query.trim().toLowerCase();
    const f=allNotes.filter(n=>!q||n.title?.toLowerCase().includes(q)||n.up?.toLowerCase().includes(q)||n.tags?.some(t=>t.toLowerCase().includes(q)));
    const m=new Map<string,Note[]>();
    f.forEach(n=>{const cat=n.category||'未分类';if(!m.has(cat))m.set(cat,[]);m.get(cat)!.push(n);});
    return Array.from(m.entries()).sort((a,b)=>a[0].localeCompare(b[0]));
  },[allNotes,query]);
  const regenMoc=async()=>{setBusy(true);setNotice('');try{await apiClient.post('/api/notes/moc');setNotice('MOC已生成');}catch(e){setNotice(`失败: ${e}`);}finally{setBusy(false);}};
  if(loading) return <Spinner/>;
  if(error) return <ErrorBox message={error}/>;
  return (
    <div className="space-y-4">
      {notice && <div className="card text-sm text-slate-300">{notice}</div>}
      <div className="card flex flex-wrap items-center gap-3">
        <div className="relative flex-1 min-w-48">
          <Search size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-slate-500"/>
          <input className="w-full pl-8" placeholder="搜索标题/UP主/标签..." value={query} onChange={e=>setQuery(e.target.value)}/>
        </div>
        <button className="btn btn-primary" disabled={busy} onClick={regenMoc}>{busy?<RefreshCw size={14} className="animate-spin"/>:<FolderTree size={14}/>} 生成MOC</button>
      </div>
      {grouped.length===0 ? <div className="card text-center text-slate-500 text-sm py-8">暂无笔记</div> :
        grouped.map(([cat,notes])=>(
          <div key={cat} className="card">
            <div className="flex items-center gap-2 mb-3"><Layers size={16} className="text-blue-400"/><h3 className="font-semibold text-white">{cat}</h3><span className="text-xs text-slate-500">({notes.length})</span></div>
            <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-3">
              {notes.map((n,i)=>(
                <div key={`${n.path}-${i}`} className="rounded-lg border border-slate-800 p-3 bg-slate-900/60">
                  <div className="text-white text-sm truncate" title={n.title}>{n.title||'(无标题)'}</div>
                  <div className="text-xs text-slate-500 mt-1">UP: {n.up||'-'}</div>
                  <div className="flex flex-wrap gap-1 mt-2">{n.tags?.map(t=><span key={t} className="badge badge-gray text-xs"><Tag size={10} className="inline mr-1"/>{t}</span>)}{(!n.tags||n.tags.length===0)&&<span className="text-xs text-slate-600">无标签</span>}</div>
                </div>
              ))}
            </div>
          </div>
        ))
      }
    </div>
  );
}

/* ─── 5. Review ─── */
export function Review() {
  const { data, loading, error, reload } = useAsync<any>(()=>apiClient.get('/api/review/status'));
  const [busy,setBusy]=useState(false); const [notice,setNotice]=useState('');
  const s=data||{};
  const trigger=async()=>{if(!confirm('启动审查？'))return;setBusy(true);setNotice('');try{const r=await apiClient.post<any>('/api/review?mode=auto&batch_size=5');setNotice(`审查完成: ${r.reviewed_count}篇`);reload();}catch(e){setNotice(`失败: ${e}`);}finally{setBusy(false);}};
  if(loading) return <Spinner/>;
  if(error) return <ErrorBox message={error}/>;
  return (
    <div className="space-y-4">
      {notice && <div className="card text-sm text-slate-300">{notice}</div>}
      <div className="card flex items-center justify-between">
        <div><h3 className="font-semibold text-white mb-1">自动审查</h3><p className="text-xs text-slate-400">扫描笔记，提取待验证声明</p></div>
        <button className="btn btn-primary" disabled={busy} onClick={trigger}>{busy?<RefreshCw size={14} className="animate-spin"/>:<Play size={14}/>} 启动审查</button>
      </div>
      <div className="grid grid-cols-3 gap-4">
        <div className="card text-center"><div className="text-xs text-slate-400">已审查</div><div className="text-3xl font-bold text-green-400 mt-1">{s.notes_reviewed||0}</div></div>
        <div className="card text-center"><div className="text-xs text-slate-400">待验证</div><div className="text-3xl font-bold text-yellow-400 mt-1">{s.pending_claims||0}</div></div>
        <div className="card text-center"><div className="text-xs text-slate-400">已解决</div><div className="text-3xl font-bold text-white mt-1">{s.resolved_claims||0}</div></div>
      </div>
    </div>
  );
}

/* ─── 6. Claims ─── */
export function Claims() {
  const { data, loading, error, reload } = useAsync<PendingClaim[]>(()=>apiClient.get('/api/review/pending'));
  const [busyId,setBusyId]=useState<number|null>(null); const [notice,setNotice]=useState('');
  const claims=data||[];
  const resolve=async(id:number,action:string)=>{setBusyId(id);setNotice('');try{await apiClient.post('/api/review/resolve',{claim_id:id,action});setNotice(`已处理: ${action}`);reload();}catch(e){setNotice(`失败: ${e}`);}finally{setBusyId(null);}};
  if(loading) return <Spinner/>;
  if(error) return <ErrorBox message={error}/>;
  return (
    <div className="space-y-4">
      {notice && <div className="card text-sm text-slate-300">{notice}</div>}
      <div className="flex items-center justify-between"><span className="text-sm text-slate-400">共 {claims.length} 条</span><button className="btn btn-ghost text-xs" onClick={reload}><RefreshCw size={14}/> 刷新</button></div>
      {claims.length===0 ? <div className="card text-center text-slate-500 text-sm py-8">暂无待验证声明</div> :
        claims.map(c=>(
          <div key={c.id} className="card">
            <div className="flex items-center gap-2 mb-2"><span className="badge badge-blue">{c.claim_type}</span><StatusBadge status={c.status}/></div>
            <p className="text-slate-200 text-sm mb-2">{c.claim}</p>
            <div className="text-xs text-slate-500 mb-3">来源: {c.content_title||`#${c.content_id}`}{c.category?` | ${c.category}`:''}</div>
            <div className="flex gap-2 pt-3 border-t border-slate-800">
              <button className="btn btn-success text-xs" disabled={busyId===c.id} onClick={()=>resolve(c.id,'confirm')}><CheckCircle size={12}/> 确认</button>
              <button className="btn btn-danger text-xs" disabled={busyId===c.id} onClick={()=>{if(confirm('移除？'))resolve(c.id,'remove')}}><Trash2 size={12}/> 移除</button>
            </div>
          </div>
        ))
      }
    </div>
  );
}

/* ─── 7. Settings ─── */
export function Settings() {
  const { data, loading, error, reload } = useAsync<SettingsType>(()=>apiClient.get('/api/settings'));
  const [saving,setSaving]=useState(false); const [notice,setNotice]=useState('');
  const [vaultResult,setVaultResult]=useState(''); const [testingVault,setTestingVault]=useState(false);
  const s=data;
  const setVal=(key:string,val:any)=>{if(s)(s as any)[key]=val;};
  const save=async()=>{if(!s)return;setSaving(true);setNotice('');
    try{
      await apiClient.put('/api/settings/vault_path',{value:s.vault_path});
      await apiClient.put('/api/settings/ai_config',{value:s.ai_config});
      await apiClient.put('/api/settings/whisper_config',{value:s.whisper_config});
      await apiClient.put('/api/settings/sessdata',{value:s.sessdata});
      await apiClient.put('/api/settings/wechat_method',{value:s.wechat_method});
      await apiClient.put('/api/settings/schedule_config',{value:s.schedule_config});
      await apiClient.put('/api/settings/ad_filter_prompt',{value:s.ad_filter_prompt});
      await apiClient.put('/api/settings/domain_taxonomy',{value:s.domain_taxonomy});
      setNotice('保存成功');setTimeout(()=>setNotice(''),3000);reload();
    }catch(e){setNotice(`失败: ${e instanceof Error?e.message:String(e)}`);}finally{setSaving(false);}};
  const testVault=async()=>{if(!s)return;setTestingVault(true);setVaultResult('');try{const r=await apiClient.post<{valid:boolean}>('/api/settings/test-vault',{path:s.vault_path});setVaultResult(r.valid?'✓ 有效':'✗ 失败');}catch(e){setVaultResult(`✗ ${e}`);}finally{setTestingVault(false);}};
  if(loading) return <Spinner/>;
  if(error) return <ErrorBox message={error}/>;
  if(!s) return <ErrorBox message="No settings"/>;
  return (
    <div className="space-y-4 max-w-4xl">
      {notice && <div className="card text-sm text-slate-300">{notice}</div>}
      <div className="card">
        <h3 className="font-semibold text-white mb-4">Obsidian Vault</h3>
        <label className="block text-xs text-slate-400 mb-1">Vault 路径</label>
        <div className="flex gap-2">
          <input className="flex-1" value={s.vault_path} onChange={e=>setVal('vault_path',e.target.value)}/>
          <button className="btn btn-ghost text-xs" disabled={testingVault} onClick={testVault}>{testingVault?<RefreshCw size={14} className="animate-spin"/>:<RefreshCw size={14}/>} 测试</button>
        </div>
        {vaultResult && <p className={`text-xs mt-1 ${vaultResult.startsWith('✓')?'text-green-400':'text-red-400'}`}>{vaultResult}</p>}
      </div>
      <div className="card">
        <h3 className="font-semibold text-white mb-4">AI 配置</h3>
        <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
          <div><label className="block text-xs text-slate-400 mb-1">API Base</label><input className="w-full" value={s.ai_config.api_base} onChange={e=>{s.ai_config.api_base=e.target.value;setVal('ai_config',{...s.ai_config})}}/></div>
          <div><label className="block text-xs text-slate-400 mb-1">文本模型</label><input className="w-full" value={s.ai_config.text_model} onChange={e=>{s.ai_config.text_model=e.target.value;setVal('ai_config',{...s.ai_config})}}/></div>
          <div><label className="block text-xs text-slate-400 mb-1">视觉模型</label><input className="w-full" value={s.ai_config.vision_model} onChange={e=>{s.ai_config.vision_model=e.target.value;setVal('ai_config',{...s.ai_config})}}/></div>
          <div><label className="block text-xs text-slate-400 mb-1">Temperature</label><input type="number" step="0.1" className="w-full" value={s.ai_config.temperature} onChange={e=>{s.ai_config.temperature=parseFloat(e.target.value);setVal('ai_config',{...s.ai_config})}}/></div>
          <div><label className="block text-xs text-slate-400 mb-1">Max Tokens</label><input type="number" className="w-full" value={s.ai_config.max_tokens} onChange={e=>{s.ai_config.max_tokens=parseInt(e.target.value);setVal('ai_config',{...s.ai_config})}}/></div>
        </div>
      </div>
      <div className="card">
        <h3 className="font-semibold text-white mb-4">Whisper 配置</h3>
        <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
          <div><label className="block text-xs text-slate-400 mb-1">模式</label><select className="w-full" value={s.whisper_config.mode} onChange={e=>{s.whisper_config.mode=e.target.value;setVal('whisper_config',{...s.whisper_config})}}><option value="cloud">云端</option><option value="local">本地</option></select></div>
          <div><label className="block text-xs text-slate-400 mb-1">模型大小</label><select className="w-full" value={s.whisper_config.model_size} onChange={e=>{s.whisper_config.model_size=e.target.value;setVal('whisper_config',{...s.whisper_config})}}><option value="base">base</option><option value="small">small</option><option value="medium">medium</option></select></div>
          <div><label className="block text-xs text-slate-400 mb-1">语言</label><select className="w-full" value={s.whisper_config.language} onChange={e=>{s.whisper_config.language=e.target.value;setVal('whisper_config',{...s.whisper_config})}}><option value="zh">中文</option><option value="en">English</option></select></div>
        </div>
      </div>
      <div className="card">
        <h3 className="font-semibold text-white mb-4">平台凭据</h3>
        <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
          <div><label className="block text-xs text-slate-400 mb-1">B站 SESSDATA</label><input type="password" className="w-full" value={s.sessdata} onChange={e=>setVal('sessdata',e.target.value)} placeholder="SESSDATA cookie"/></div>
          <div><label className="block text-xs text-slate-400 mb-1">公众号采集方式</label><select className="w-full" value={s.wechat_method} onChange={e=>setVal('wechat_method',e.target.value)}><option value="manual">手动</option><option value="sogou">搜狗微信</option></select></div>
        </div>
      </div>
      <div className="card">
        <h3 className="font-semibold text-white mb-4">调度配置</h3>
        <label className="block text-xs text-slate-400 mb-1">每日检查时间</label>
        <input type="time" className="w-full md:w-48" value={s.schedule_config.check_time} onChange={e=>{s.schedule_config.check_time=e.target.value;setVal('schedule_config',{...s.schedule_config})}}/>
      </div>
      <div className="card">
        <h3 className="font-semibold text-white mb-4">广告过滤提示词</h3>
        <textarea className="w-full font-mono text-xs" rows={4} value={s.ad_filter_prompt} onChange={e=>setVal('ad_filter_prompt',e.target.value)}/>
      </div>
      <div className="card">
        <h3 className="font-semibold text-white mb-4">领域分类法 (JSON)</h3>
        <textarea className="w-full font-mono text-xs" rows={10} value={JSON.stringify(s.domain_taxonomy,null,2)} readOnly/>
      </div>
      <div className="flex items-center gap-3">
        <button className="btn btn-primary" disabled={saving} onClick={save}>{saving?<RefreshCw size={14} className="animate-spin"/>:<Save size={14}/>} 保存设置</button>
        <button className="btn btn-ghost" onClick={reload}>重置</button>
      </div>
    </div>
  );
}
