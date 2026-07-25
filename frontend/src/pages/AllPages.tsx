import { useCallback, useEffect, useMemo, useState } from 'react';
import {
  AlertTriangle, CheckCircle, Clock, Eye, FileText, FolderTree,
  Layers, Play, Plus, RefreshCw, Save, Search, Tag, Trash2, Upload, XCircle,
} from 'lucide-react';
import { apiClient } from '../lib/api';
import type { Content, Creator, Note, PendingClaim, ProcessStats, Settings as SettingsType, Task } from '../lib/types';

const PAGE_SIZE = 20;

function Spinner({ label = '加载中...' }: { label?: string }) {
  return (
    <div className="flex items-center gap-2 text-slate-400 text-sm py-4">
      <RefreshCw className="animate-spin" size={16} /><span>{label}</span>
    </div>
  );
}

function ErrorBox({ message }: { message: string }) {
  return (
    <div className="card border-red-900 text-red-300 text-sm">
      <div className="flex items-center gap-2"><AlertTriangle size={16} /><span>{message}</span></div>
    </div>
  );
}

function StatusBadge({ status }: { status: string }) {
  const map: Record<string, string> = {
    done: 'badge-green', completed: 'badge-green', confirmed: 'badge-green', reviewed: 'badge-green',
    failed: 'badge-red', error: 'badge-red', removed: 'badge-red',
    pending: 'badge-yellow', unreviewed: 'badge-yellow',
    fetching: 'badge-blue', transcribing: 'badge-blue', cleaning: 'badge-blue',
    classifying: 'badge-blue', extracting: 'badge-blue', processing: 'badge-blue', corrected: 'badge-blue',
  };
  return <span className={`badge ${map[(status||'').toLowerCase()] || 'badge-gray'}`}>{status || '-'}</span>;
}

function formatDuration(seconds?: number): string {
  if (!seconds || seconds <= 0) return '-';
  const m = Math.floor(seconds / 60); const s = Math.floor(seconds % 60);
  return `${m}:${s.toString().padStart(2,'0')}`;
}

function safeDate(v?: string): string {
  if (!v) return '-';
  const d = new Date(v);
  if (Number.isNaN(d.getTime())) return v;
  return d.toLocaleString('zh-CN', { hour12: false });
}

function useAsync<T>(fetcher: () => Promise<T>, deps: unknown[] = []) {
  const cb = useCallback(fetcher, deps);
  const [data, setData] = useState<T | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const run = useCallback(() => {
    let alive = true; setLoading(true); setError('');
    cb().then(d => { if (alive) { setData(d); setLoading(false); } })
      .catch((e: unknown) => { if (alive) { setError(e instanceof Error ? e.message : String(e)); setLoading(false); } });
    return () => { alive = false; };
  }, [cb]);
  useEffect(() => run(), [run]);
  return { data, loading, error, reload: run };
}

/* ─── 1. Dashboard ─── */
export function Dashboard() {
  const stats = useAsync<ProcessStats>(() => apiClient.get('/api/process/stats'));
  const creators = useAsync<Creator[]>(() => apiClient.get('/api/creators'));
  const s = stats.data; const recent = (creators.data || []).slice(0, 6);
  const cards: {label:string;value:number;cls:string}[] = s ? [
    {label:'创作号总数',value:creators.data?.length||0,cls:'badge-blue'},
    {label:'内容总数',value:s.total,cls:'badge-gray'},
    {label:'已完成',value:s.done,cls:'badge-green'},
    {label:'失败',value:s.failed,cls:'badge-red'},
    {label:'待处理',value:s.pending,cls:'badge-yellow'},
    {label:'处理中',value:(s.fetching||0)+(s.transcribing||0)+(s.cleaning||0)+(s.classifying||0)+(s.extracting||0),cls:'badge-blue'},
  ] : [];
  if (stats.loading || creators.loading) return <Spinner />;
  if (stats.error) return <ErrorBox message={stats.error} />;
  return (
    <div className="space-y-6">
      <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-6 gap-4">
        {cards.map(c => (
          <div key={c.label} className="card">
            <div className="text-xs text-slate-400">{c.label}</div>
            <div className="text-2xl font-bold text-white mt-1">{c.value}</div>
          </div>
        ))}
      </div>
      <div className="card">
        <h3 className="font-semibold text-white mb-3">最近创作号</h3>
        {recent.length === 0 ? <p className="text-sm text-slate-500">暂无数据</p> : (
          <ul className="space-y-2">
            {recent.map(c => (
              <li key={c.id} className="flex items-center justify-between text-sm">
                <div className="flex items-center gap-2"><span className="text-white">{c.name}</span><span className="text-slate-500 text-xs">{c.platform}</span></div>
                <span className="text-slate-500 text-xs">{safeDate(c.last_checked)}</span>
              </li>
            ))}
          </ul>
        )}
      </div>
    </div>
  );
}

/* ─── 2. Creators ─── */
export function Creators() {
  const { data, loading, error, reload } = useAsync<Creator[]>(() => apiClient.get('/api/creators'));
  const [biliUid, setBiliUid] = useState(''); const [biliName, setBiliName] = useState('');
  const [wcUid, setWcUid] = useState(''); const [wcName, setWcName] = useState('');
  const [busy, setBusy] = useState(false); const [notice, setNotice] = useState('');
  const creators = data || [];
  const bili = creators.filter(c => c.platform === 'bilibili');
  const wc = creators.filter(c => c.platform === 'wechat');

  const add = async (platform: string, uid: string, name: string) => {
    if (!uid.trim()) return; setBusy(true); setNotice('');
    try {
      await apiClient.post('/api/creators', { platform, uid: uid.trim(), name: name.trim() });
      setNotice('添加成功'); reload();
    } catch (e) { setNotice(`失败: ${e instanceof Error ? e.message : String(e)}`); }
    finally { setBusy(false); }
  };
  const del = async (id: number, name: string) => {
    if (!confirm(`删除「${name}」？`)) return; setBusy(true);
    try { await apiClient.del(`/api/creators/${id}`); setNotice('已删除'); reload(); }
    catch (e) { setNotice(`失败: ${e instanceof Error ? e.message : String(e)}`); }
    finally { setBusy(false); }
  };
  const check = async (c: Creator) => {
    setBusy(true); setNotice('');
    try { const r = await apiClient.get<any>(`/api/creators/${c.id}/check`); setNotice(`检查完成: ${r.new_count} 个新视频`); reload(); }
    catch (e) { setNotice(`失败: ${e instanceof Error ? e.message : String(e)}`); }
    finally { setBusy(false); }
  };

  if (loading) return <Spinner />;
  if (error) return <ErrorBox message={error} />;

  const Col = ({ title, list, uid, setUid, name, setName, platform }: any) => (
    <div className="card flex flex-col">
      <h3 className="font-semibold text-white mb-3">{title}</h3>
      <div className="flex gap-2 mb-4">
        <input className="flex-1" placeholder="UID" value={uid} onChange={e=>setUid(e.target.value)} />
        <input className="flex-1" placeholder="名称(可选)" value={name} onChange={e=>setName(e.target.value)} />
        <button className="btn btn-primary" disabled={busy||!uid.trim()} onClick={()=>add(platform,uid,name)}>
          <Plus size={14} /> 添加
        </button>
      </div>
      <div className="space-y-2 overflow-y-auto max-h-[60vh]">
        {list.length === 0 ? <p className="text-sm text-slate-500 py-4 text-center">暂无</p> :
          list.map((c: Creator) => (
            <div key={c.id} className="rounded-lg border border-slate-800 p-3 bg-slate-900/60">
              <div className="flex items-start justify-between gap-2">
                <div className="min-w-0">
                  <span className="text-white font-medium">{c.name}</span>
                  <span className="text-xs text-slate-500 ml-2">{c.uid}</span>
                  <div className="flex gap-1.5 mt-1">
                    <span className="badge badge-blue">{c.update_strategy}</span>
                    <span className="badge badge-yellow">{c.priority}</span>
                  </div>
                  <div className="text-xs text-slate-500 mt-1">最后检查: {safeDate(c.last_checked)}</div>
                </div>
                <div className="flex gap-1">
                  <button className="btn btn-ghost text-xs px-2 py-1" disabled={busy} onClick={()=>check(c)}><RefreshCw size={12} /></button>
                  <button className="btn btn-danger text-xs px-2 py-1" disabled={busy} onClick={()=>del(c.id,c.name)}><Trash2 size={12} /></button>
                </div>
              </div>
            </div>
          ))
        }
      </div>
    </div>
  );

  return (
    <div className="space-y-4">
      {notice && <div className="card text-sm text-slate-300">{notice}</div>}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        <Col title="B站 bilibili" list={bili} uid={biliUid} setUid={setBiliUid} name={biliName} setName={setBiliName} platform="bilibili" />
        <Col title="公众号 WeChat" list={wc} uid={wcUid} setUid={setWcUid} name={wcName} setName={setWcName} platform="wechat" />
      </div>
    </div>
  );
}

/* ─── 3. ContentList ─── */
export function ContentList() {
  const [page, setPage] = useState(1);
  const [statusFilter, setStatusFilter] = useState('');
  const [actionId, setActionId] = useState<number|null>(null);
  const [notice, setNotice] = useState('');
  const [bvidInput, setBvidInput] = useState('');
  const [bvidBusy, setBvidBusy] = useState(false);
  const path = `/api/contents?page=${page}&page_size=${PAGE_SIZE}${statusFilter ? `&status=${statusFilter}` : ''}`;
  const { data, loading, error, reload } = useAsync<any>(() => apiClient.get(path), [page, statusFilter]);

  const items: Content[] = data?.items || [];
  const total = data?.total || 0;
  const totalPages = Math.max(1, Math.ceil(total / PAGE_SIZE));

  const processOne = async (id: number) => {
    setActionId(id); setNotice('');
    try { await apiClient.post(`/api/process/${id}`); setNotice(`已处理: #${id}`); reload(); }
    catch (e) { setNotice(`失败: ${e instanceof Error ? e.message : String(e)}`); }
    finally { setActionId(null); }
  };

  const deleteContent = async (id: number, title: string) => {
    if (!confirm(`删除「${title||'#'+id}」？`)) return;
    setActionId(id); setNotice('');
    try { await apiClient.del(`/api/contents/${id}`); setNotice('已删除'); reload(); }
    catch (e) { setNotice(`失败: ${e instanceof Error ? e.message : String(e)}`); }
    finally { setActionId(null); }
  };

  const processBvid = async () => {
    const bvid = bvidInput.trim();
    if (!bvid) return;
    setBvidBusy(true); setNotice('');
    try { const r = await apiClient.post<any>(`/api/process/bvid/${bvid}`); setNotice(r.success ? `处理成功: ${r.title||bvid}` : `处理失败: ${r.error||''}`); setBvidInput(''); reload(); }
    catch (e) { setNotice(`失败: ${e instanceof Error ? e.message : String(e)}`); }
    finally { setBvidBusy(false); }
  };

  if (loading) return <Spinner />;
  if (error) return <ErrorBox message={error} />;

  return (
    <div className="space-y-4">
      {notice && <div className="card text-sm text-slate-300">{notice}</div>}
      <div className="card">
        <div className="flex items-center gap-3 mb-4">
          <div className="flex gap-2 flex-1">
            <input
              className="flex-1 max-w-xs"
              placeholder="输入BV号直接处理 (如 BV1xxxxx)"
              value={bvidInput}
              onChange={e=>setBvidInput(e.target.value)}
              onKeyDown={e=>{if(e.key==='Enter')processBvid()}}
            />
            <button
              className="btn btn-primary text-xs whitespace-nowrap"
              disabled={bvidBusy||!bvidInput.trim()}
              onClick={processBvid}
            >
              {bvidBusy ? <RefreshCw size={14} className="animate-spin" /> : <Play size={14} />} 处理
            </button>
          </div>
          <select value={statusFilter} onChange={e=>{setStatusFilter(e.target.value);setPage(1);}}>
            <option value="">全部状态</option>
            <option value="pending">pending</option><option value="done">done</option><option value="failed">failed</option>
            </select>
            <span className="text-xs text-slate-500">共 {total} 条</span>
            </div>
            <div className="overflow-x-auto">
            <table className="w-full text-sm">
            <thead><tr className="text-left text-slate-400 border-b border-slate-800">
              <th className="py-2 pr-3">标题</th><th className="py-2 pr-3">状态</th><th className="py-2 pr-3">分类</th>
              <th className="py-2 pr-3">UP主</th><th className="py-2 pr-3">时长</th><th className="py-2 pr-3">操作</th>
            </tr></thead>
            <tbody>
              {items.length === 0 ? <tr><td colSpan={6} className="py-6 text-center text-slate-500">暂无数据</td></tr> :
                items.map(c => (
                  <tr key={c.id} className="border-b border-slate-800/60">
                    <td className="py-2 pr-3 max-w-xs truncate" title={c.title}>{c.title || '-'}</td>
                    <td className="py-2 pr-3"><StatusBadge status={c.status} /></td>
                    <td className="py-2 pr-3 text-slate-400">{c.category || '-'}</td>
                    <td className="py-2 pr-3 text-slate-400">{c.up_name || `#${c.creator_id}`}</td>
                    <td className="py-2 pr-3 text-slate-400">{formatDuration(c.duration)}</td>
                    <td className="py-2 pr-3">
                      <div className="flex items-center gap-1">
                        {(c.status === 'pending' || c.status === 'failed') ? (
                          <button className="btn btn-primary text-xs px-2 py-1" disabled={actionId===c.id} onClick={()=>processOne(c.id)}>
                            {actionId===c.id ? <RefreshCw size={12} className="animate-spin" /> : <Play size={12} />} 处理
                          </button>
                        ) : c.status === 'done' ? <CheckCircle size={14} className="text-green-400" /> : null}
                        <button className="btn btn-danger text-xs px-2 py-1" disabled={actionId===c.id} onClick={()=>deleteContent(c.id,c.title)}>
                          <Trash2 size={12} />
                        </button>
                      </div>
                    </td>
                  </tr>
                ))
              }
            </tbody>
            </table>
            </div>
        {totalPages > 1 && (
          <div className="flex items-center justify-end gap-2 mt-4 text-sm">
            <button className="btn btn-ghost text-xs" disabled={page<=1} onClick={()=>setPage(page-1)}>上一页</button>
            <span className="text-slate-400">{page} / {totalPages}</span>
            <button className="btn btn-ghost text-xs" disabled={page>=totalPages} onClick={()=>setPage(page+1)}>下一页</button>
          </div>
        )}
      </div>
    </div>
  );
}

/* ─── 4. Processing ─── */
export function Processing() {
  const stats = useAsync<ProcessStats>(() => apiClient.get('/api/process/stats'));
  const tasks = useAsync<Task[]>(() => apiClient.get('/api/process/queue'));
  const [retryId, setRetryId] = useState<number|null>(null);
  const [notice, setNotice] = useState('');
  const s = stats.data; const taskList = tasks.data || [];
  const cards: {label:string;value:number;color:string}[] = s ? [
    {label:'总数',value:s.total,color:'text-white'},{label:'待处理',value:s.pending,color:'text-yellow-400'},
    {label:'完成',value:s.done,color:'text-green-400'},{label:'失败',value:s.failed,color:'text-red-400'},
  ] : [];
  const retry = async (id: number) => {
    setRetryId(id); setNotice('');
    try { await apiClient.post(`/api/process/retry/${id}`); setNotice('已重试'); stats.reload(); tasks.reload(); }
    catch (e) { setNotice(`失败: ${e instanceof Error ? e.message : String(e)}`); }
    finally { setRetryId(null); }
  };
  const delTask = async (id: number) => {
    if (!confirm('删除此任务记录？')) return;
    try { await apiClient.del(`/api/process/queue/${id}`); tasks.reload(); }
    catch (e) { setNotice(`失败: ${e instanceof Error ? e.message : String(e)}`); }
  };
  return (
    <div className="space-y-4">
      {notice && <div className="card text-sm text-slate-300">{notice}</div>}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
        {cards.map(c => (
          <div key={c.label} className="card text-center">
            <div className="text-xs text-slate-400 mb-1">{c.label}</div>
            <div className={`text-2xl font-bold ${c.color}`}>{c.value}</div>
          </div>
        ))}
      </div>
      <div className="card">
        <div className="flex items-center justify-between mb-4">
          <h3 className="font-semibold text-white">任务队列</h3>
          <button className="btn btn-ghost text-xs" onClick={tasks.reload}><RefreshCw size={14} /> 刷新</button>
        </div>
        {taskList.length === 0 ? <p className="text-sm text-slate-500 text-center py-4">队列为空</p> : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead><tr className="text-left text-slate-400 border-b border-slate-800">
                <th className="py-2 pr-3">ID</th><th className="py-2 pr-3">类型</th><th className="py-2 pr-3">状态</th>
                <th className="py-2 pr-3">错误</th><th className="py-2 pr-3">操作</th>
              </tr></thead>
              <tbody>
                {taskList.map((t,i) => (
                  <tr key={t.id ?? i} className="border-b border-slate-800/60">
                    <td className="py-2 pr-3">#{t.content_id}</td>
                    <td className="py-2 pr-3 text-slate-300">{t.task_type}</td>
                    <td className="py-2 pr-3"><StatusBadge status={t.status} /></td>
                    <td className="py-2 pr-3 text-red-400 text-xs max-w-xs truncate" title={t.error}>{t.error || '-'}</td>
                    <td className="py-2 pr-3">
                      <div className="flex items-center gap-1">
                        {t.status === 'failed' && (
                          <button className="btn btn-primary text-xs px-2 py-1" disabled={retryId===t.content_id} onClick={()=>retry(t.content_id)}>
                            <RefreshCw size={12} /> 重试
                          </button>
                        )}
                        {t.id && <button className="btn btn-danger text-xs px-2 py-1" onClick={()=>delTask(t.id!)}><Trash2 size={12} /></button>}
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  );
}

/* ─── 5. Notes ─── */
export function Notes() {
  const { data, loading, error, reload } = useAsync<{notes:Note[],count:number}>(() => apiClient.get('/api/notes'));
  const [query, setQuery] = useState(''); const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState('');
  const allNotes = data?.notes || [];
  const grouped = useMemo(() => {
    const q = query.trim().toLowerCase();
    const filtered = allNotes.filter(n => !q || n.title?.toLowerCase().includes(q) || n.up?.toLowerCase().includes(q) || n.tags?.some(t=>t.toLowerCase().includes(q)));
    const map = new Map<string, Note[]>();
    filtered.forEach(n => { const cat = n.category || '未分类'; if (!map.has(cat)) map.set(cat, []); map.get(cat)!.push(n); });
    return Array.from(map.entries()).sort((a,b) => a[0].localeCompare(b[0]));
  }, [allNotes, query]);

  const regenMoc = async () => {
    setBusy(true); setNotice('');
    try { await apiClient.post('/api/notes/moc'); setNotice('MOC已重新生成'); }
    catch (e) { setNotice(`失败: ${e instanceof Error ? e.message : String(e)}`); }
    finally { setBusy(false); }
  };

  if (loading) return <Spinner />;
  if (error) return <ErrorBox message={error} />;

  return (
    <div className="space-y-4">
      {notice && <div className="card text-sm text-slate-300">{notice}</div>}
      <div className="card flex flex-wrap items-center gap-3">
        <div className="relative flex-1 min-w-48">
          <Search size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-slate-500" />
          <input className="w-full pl-8" placeholder="搜索标题/UP主/标签..." value={query} onChange={e=>setQuery(e.target.value)} />
        </div>
        <button className="btn btn-primary" disabled={busy} onClick={regenMoc}>
          {busy ? <RefreshCw size={14} className="animate-spin" /> : <FolderTree size={14} />} 生成MOC
        </button>
      </div>
      {grouped.length === 0 ? <div className="card text-center text-slate-500 text-sm py-8">暂无笔记</div> :
        grouped.map(([cat, notes]) => (
          <div key={cat} className="card">
            <div className="flex items-center gap-2 mb-3">
              <Layers size={16} className="text-blue-400" /><h3 className="font-semibold text-white">{cat}</h3>
              <span className="text-xs text-slate-500">({notes.length})</span>
            </div>
            <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-3">
              {notes.map((n,i) => (
                <div key={`${n.path}-${i}`} className="rounded-lg border border-slate-800 p-3 bg-slate-900/60">
                  <div className="text-white text-sm truncate" title={n.title}>{n.title || '(无标题)'}</div>
                  <div className="text-xs text-slate-500 mt-1">UP: {n.up || '-'}</div>
                  <div className="flex flex-wrap gap-1 mt-2">
                    {n.tags?.map(t => <span key={t} className="badge badge-gray text-xs"><Tag size={10} className="inline mr-1" />{t}</span>)}
                    {(!n.tags || n.tags.length === 0) && <span className="text-xs text-slate-600">无标签</span>}
                  </div>
                </div>
              ))}
            </div>
          </div>
        ))
      }
    </div>
  );
}

/* ─── 6. Review ─── */
export function Review() {
  const { data, loading, error, reload } = useAsync<any>(() => apiClient.get('/api/review/status'));
  const [busy, setBusy] = useState(false); const [notice, setNotice] = useState('');
  const s = data || {};
  const trigger = async () => {
    if (!confirm('启动审查？')) return; setBusy(true); setNotice('');
    try { const r = await apiClient.post<any>('/api/review?mode=auto&batch_size=5'); setNotice(`审查完成: ${r.reviewed_count}篇`); reload(); }
    catch (e) { setNotice(`失败: ${e instanceof Error ? e.message : String(e)}`); }
    finally { setBusy(false); }
  };
  if (loading) return <Spinner />;
  if (error) return <ErrorBox message={error} />;
  return (
    <div className="space-y-4">
      {notice && <div className="card text-sm text-slate-300">{notice}</div>}
      <div className="card flex items-center justify-between">
        <div><h3 className="font-semibold text-white mb-1">自动审查</h3><p className="text-xs text-slate-400">扫描笔记，提取待验证声明</p></div>
        <button className="btn btn-primary" disabled={busy} onClick={trigger}>
          {busy ? <RefreshCw size={14} className="animate-spin" /> : <Play size={14} />} 启动审查
        </button>
      </div>
      <div className="grid grid-cols-3 gap-4">
        <div className="card text-center"><div className="text-xs text-slate-400">已审查</div><div className="text-3xl font-bold text-green-400 mt-1">{s.notes_reviewed||0}</div></div>
        <div className="card text-center"><div className="text-xs text-slate-400">待验证</div><div className="text-3xl font-bold text-yellow-400 mt-1">{s.pending_claims||0}</div></div>
        <div className="card text-center"><div className="text-xs text-slate-400">已解决</div><div className="text-3xl font-bold text-white mt-1">{s.resolved_claims||0}</div></div>
      </div>
    </div>
  );
}

/* ─── 7. Claims ─── */
export function Claims() {
  const { data, loading, error, reload } = useAsync<PendingClaim[]>(() => apiClient.get('/api/review/pending'));
  const [busyId, setBusyId] = useState<number|null>(null);
  const [notice, setNotice] = useState('');
  const claims = data || [];
  const resolve = async (id: number, action: string) => {
    setBusyId(id); setNotice('');
    try { await apiClient.post('/api/review/resolve', { claim_id: id, action }); setNotice(`已处理: ${action}`); reload(); }
    catch (e) { setNotice(`失败: ${e instanceof Error ? e.message : String(e)}`); }
    finally { setBusyId(null); }
  };
  if (loading) return <Spinner />;
  if (error) return <ErrorBox message={error} />;
  return (
    <div className="space-y-4">
      {notice && <div className="card text-sm text-slate-300">{notice}</div>}
      <div className="flex items-center justify-between">
        <span className="text-sm text-slate-400">共 {claims.length} 条</span>
        <button className="btn btn-ghost text-xs" onClick={reload}><RefreshCw size={14} /> 刷新</button>
      </div>
      {claims.length === 0 ? <div className="card text-center text-slate-500 text-sm py-8">暂无待验证声明</div> :
        claims.map(c => (
          <div key={c.id} className="card">
            <div className="flex items-center gap-2 mb-2">
              <span className="badge badge-blue">{c.claim_type}</span>
              <StatusBadge status={c.status} />
            </div>
            <p className="text-slate-200 text-sm mb-2">{c.claim}</p>
            <div className="text-xs text-slate-500 mb-3">来源: {c.content_title || `#${c.content_id}`}{c.category ? ` | ${c.category}` : ''}</div>
            <div className="flex gap-2 pt-3 border-t border-slate-800">
              <button className="btn btn-success text-xs" disabled={busyId===c.id} onClick={()=>resolve(c.id,'confirm')}><CheckCircle size={12} /> 确认</button>
              <button className="btn btn-danger text-xs" disabled={busyId===c.id} onClick={()=>{if(confirm('移除？'))resolve(c.id,'remove')}}><Trash2 size={12} /> 移除</button>
            </div>
          </div>
        ))
      }
    </div>
  );
}

/* ─── 8. Settings ─── */
export function Settings() {
  const { data, loading, error, reload } = useAsync<SettingsType>(() => apiClient.get('/api/settings'));
  const [saving, setSaving] = useState(false); const [notice, setNotice] = useState('');
  const [vaultResult, setVaultResult] = useState(''); const [testingVault, setTestingVault] = useState(false);
  const s = data;
  const setVal = (key: string, val: any) => { if (s) (s as any)[key] = val; };

  const save = async () => {
    if (!s) return; setSaving(true); setNotice('');
    try {
      await apiClient.put('/api/settings/vault_path', { value: s.vault_path });
      await apiClient.put('/api/settings/ai_config', { value: s.ai_config });
      await apiClient.put('/api/settings/whisper_config', { value: s.whisper_config });
      await apiClient.put('/api/settings/sessdata', { value: s.sessdata });
      await apiClient.put('/api/settings/wechat_method', { value: s.wechat_method });
      await apiClient.put('/api/settings/schedule_config', { value: s.schedule_config });
      await apiClient.put('/api/settings/ad_filter_prompt', { value: s.ad_filter_prompt });
      await apiClient.put('/api/settings/domain_taxonomy', { value: s.domain_taxonomy });
      setNotice('保存成功'); setTimeout(()=>setNotice(''),3000); reload();
    } catch (e) { setNotice(`失败: ${e instanceof Error ? e.message : String(e)}`); }
    finally { setSaving(false); }
  };
  const testVault = async () => {
    if (!s) return; setTestingVault(true); setVaultResult('');
    try { const r = await apiClient.post<{valid:boolean;message?:string}>('/api/settings/test-vault', { path: s.vault_path }); setVaultResult(r.valid ? '✓ 路径有效' : `✗ 失败`); }
    catch (e) { setVaultResult(`✗ ${e instanceof Error ? e.message : String(e)}`); }
    finally { setTestingVault(false); }
  };

  if (loading) return <Spinner />;
  if (error) return <ErrorBox message={error} />;
  if (!s) return <ErrorBox message="No settings data" />;

  return (
    <div className="space-y-4 max-w-4xl">
      {notice && <div className="card text-sm text-slate-300">{notice}</div>}

      <div className="card">
        <h3 className="font-semibold text-white mb-4">Obsidian Vault</h3>
        <label className="block text-xs text-slate-400 mb-1">Vault 路径</label>
        <div className="flex gap-2">
          <input className="flex-1" value={s.vault_path} onChange={e=>setVal('vault_path',e.target.value)} />
          <button className="btn btn-ghost text-xs" disabled={testingVault} onClick={testVault}>
            {testingVault ? <RefreshCw size={14} className="animate-spin" /> : <RefreshCw size={14} />} 测试
          </button>
        </div>
        {vaultResult && <p className={`text-xs mt-1 ${vaultResult.startsWith('✓')?'text-green-400':'text-red-400'}`}>{vaultResult}</p>}
      </div>

      <div className="card">
        <h3 className="font-semibold text-white mb-4">AI 配置</h3>
        <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
          <div><label className="block text-xs text-slate-400 mb-1">API Base</label><input className="w-full" value={s.ai_config.api_base} onChange={e=>{s.ai_config.api_base=e.target.value;setVal('ai_config',{...s.ai_config})}} /></div>
          <div><label className="block text-xs text-slate-400 mb-1">文本模型</label><input className="w-full" value={s.ai_config.text_model} onChange={e=>{s.ai_config.text_model=e.target.value;setVal('ai_config',{...s.ai_config})}} /></div>
          <div><label className="block text-xs text-slate-400 mb-1">视觉模型</label><input className="w-full" value={s.ai_config.vision_model} onChange={e=>{s.ai_config.vision_model=e.target.value;setVal('ai_config',{...s.ai_config})}} /></div>
          <div><label className="block text-xs text-slate-400 mb-1">Temperature</label><input type="number" step="0.1" className="w-full" value={s.ai_config.temperature} onChange={e=>{s.ai_config.temperature=parseFloat(e.target.value);setVal('ai_config',{...s.ai_config})}} /></div>
          <div><label className="block text-xs text-slate-400 mb-1">Max Tokens</label><input type="number" className="w-full" value={s.ai_config.max_tokens} onChange={e=>{s.ai_config.max_tokens=parseInt(e.target.value);setVal('ai_config',{...s.ai_config})}} /></div>
        </div>
      </div>

      <div className="card">
        <h3 className="font-semibold text-white mb-4">Whisper 配置</h3>
        <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
          <div><label className="block text-xs text-slate-400 mb-1">模式</label>
            <select className="w-full" value={s.whisper_config.mode} onChange={e=>{s.whisper_config.mode=e.target.value;setVal('whisper_config',{...s.whisper_config})}}>
              <option value="cloud">云端</option><option value="local">本地</option>
            </select>
          </div>
          <div><label className="block text-xs text-slate-400 mb-1">模型大小</label>
            <select className="w-full" value={s.whisper_config.model_size} onChange={e=>{s.whisper_config.model_size=e.target.value;setVal('whisper_config',{...s.whisper_config})}}>
              <option value="base">base</option><option value="small">small</option><option value="medium">medium</option>
            </select>
          </div>
          <div><label className="block text-xs text-slate-400 mb-1">语言</label>
            <select className="w-full" value={s.whisper_config.language} onChange={e=>{s.whisper_config.language=e.target.value;setVal('whisper_config',{...s.whisper_config})}}>
              <option value="zh">中文</option><option value="en">English</option>
            </select>
          </div>
        </div>
      </div>

      <div className="card">
        <h3 className="font-semibold text-white mb-4">平台凭据</h3>
        <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
          <div><label className="block text-xs text-slate-400 mb-1">B站 SESSDATA</label>
            <input type="password" className="w-full" value={s.sessdata} onChange={e=>setVal('sessdata',e.target.value)} placeholder="SESSDATA cookie" />
          </div>
          <div><label className="block text-xs text-slate-400 mb-1">公众号采集方式</label>
            <select className="w-full" value={s.wechat_method} onChange={e=>setVal('wechat_method',e.target.value)}>
              <option value="manual">手动</option><option value="sogou">搜狗微信</option>
            </select>
          </div>
        </div>
      </div>

      <div className="card">
        <h3 className="font-semibold text-white mb-4">调度配置</h3>
        <label className="block text-xs text-slate-400 mb-1">每日检查时间</label>
        <input type="time" className="w-full md:w-48" value={s.schedule_config.check_time} onChange={e=>{s.schedule_config.check_time=e.target.value;setVal('schedule_config',{...s.schedule_config})}} />
      </div>

      <div className="card">
        <h3 className="font-semibold text-white mb-4">广告过滤提示词</h3>
        <textarea className="w-full font-mono text-xs" rows={4} value={s.ad_filter_prompt} onChange={e=>setVal('ad_filter_prompt',e.target.value)} />
      </div>

      <div className="card">
        <h3 className="font-semibold text-white mb-4">领域分类法 (JSON)</h3>
        <textarea className="w-full font-mono text-xs" rows={10} value={JSON.stringify(s.domain_taxonomy, null, 2)} readOnly />
      </div>

      <div className="flex items-center gap-3">
        <button className="btn btn-primary" disabled={saving} onClick={save}>
          {saving ? <RefreshCw size={14} className="animate-spin" /> : <Save size={14} />} 保存设置
        </button>
        <button className="btn btn-ghost" onClick={reload}>重置</button>
      </div>
    </div>
  );
}
