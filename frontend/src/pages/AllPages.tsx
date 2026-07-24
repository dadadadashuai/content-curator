import { useCallback, useEffect, useMemo, useState } from 'react';
import {
  AlertTriangle,
  CheckCircle,
  Clock,
  Eye,
  FileText,
  FolderTree,
  Layers,
  Play,
  Plus,
  RefreshCw,
  Save,
  Search,
  Tag,
  Trash2,
  Upload,
  XCircle,
} from 'lucide-react';
import { apiClient } from '../lib/api';
import type {
  Content,
  Creator,
  Note,
  PendingClaim,
  ProcessStats,
  Settings as SettingsType,
} from '../lib/types';

/* ------------------------------------------------------------------ */
/* Shared helpers                                                      */
/* ------------------------------------------------------------------ */

const PAGE_SIZE = 20;

function Spinner({ label = '加载中...' }: { label?: string }) {
  return (
    <div className="flex items-center gap-2 text-slate-400 text-sm py-4">
      <RefreshCw className="animate-spin" size={16} />
      <span>{label}</span>
    </div>
  );
}

function ErrorBox({ message }: { message: string }) {
  return (
    <div className="card border-red-900 text-red-300 text-sm">
      <div className="flex items-center gap-2">
        <AlertTriangle size={16} />
        <span>{message}</span>
      </div>
    </div>
  );
}

function StatusBadge({ status }: { status: string }) {
  const map: Record<string, string> = {
    done: 'badge-green',
    completed: 'badge-green',
    reviewed: 'badge-green',
    confirmed: 'badge-green',
    failed: 'badge-red',
    error: 'badge-red',
    removed: 'badge-red',
    rejected: 'badge-red',
    pending: 'badge-yellow',
    unreviewed: 'badge-yellow',
    fetching: 'badge-blue',
    transcribing: 'badge-blue',
    cleaning: 'badge-blue',
    classifying: 'badge-blue',
    extracting: 'badge-blue',
    processing: 'badge-blue',
    corrected: 'badge-blue',
  };
  const cls = map[(status || '').toLowerCase()] || 'badge-gray';
  return <span className={`badge ${cls}`}>{status || '-'}</span>;
}

function formatDuration(seconds?: number): string {
  if (!seconds || seconds <= 0) return '-';
  const m = Math.floor(seconds / 60);
  const s = Math.floor(seconds % 60);
  return `${m}:${s.toString().padStart(2, '0')}`;
}

function safeDate(v?: string): string {
  if (!v) return '-';
  const d = new Date(v);
  if (Number.isNaN(d.getTime())) return v;
  return d.toLocaleString('zh-CN', { hour12: false });
}

function useAsync<T>(
  fetcher: () => Promise<T>,
  deps: unknown[] = [],
): { data: T | null; loading: boolean; error: string; reload: () => void } {
  // Inline hook to keep file self-contained and lightweight.
  // eslint-disable-next-line react-hooks/exhaustive-deps
  const cb = useCallback(fetcher, deps);
  const [data, setData] = useState<T | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');

  const run = useCallback(() => {
    let alive = true;
    setLoading(true);
    setError('');
    cb()
      .then((d) => {
        if (alive) {
          setData(d);
          setLoading(false);
        }
      })
      .catch((e: unknown) => {
        if (alive) {
          setError(e instanceof Error ? e.message : String(e));
          setLoading(false);
        }
      });
    return () => {
      alive = false;
    };
  }, [cb]);

  useEffect(() => run(), [run]);

  return { data, loading, error, reload: run };
}

interface Task {
  id?: number;
  content_id: number;
  task_type: string;
  status: string;
  started_at: string;
  finished_at: string;
  error: string;
}

/* ------------------------------------------------------------------ */
/* 1. Dashboard                                                        */
/* ------------------------------------------------------------------ */

export function Dashboard() {
  const stats = useAsync<ProcessStats>(() => apiClient.get('/api/process/stats'));
  const creators = useAsync<Creator[]>(() => apiClient.get('/api/creators'));

  const s = stats.data;
  const recent = useMemo(() => {
    const list = creators.data || [];
    return [...list]
      .sort((a, b) => (b.last_checked || '').localeCompare(a.last_checked || ''))
      .slice(0, 6);
  }, [creators.data]);

  const cards: { label: string; value: number; cls: string }[] = s
    ? [
        { label: '创作号总数', value: creators.data?.length || 0, cls: 'badge-blue' },
        { label: '内容总数', value: s.total, cls: 'badge-gray' },
        { label: '已完成', value: s.done, cls: 'badge-green' },
        { label: '失败', value: s.failed, cls: 'badge-red' },
        { label: '待处理', value: s.pending, cls: 'badge-yellow' },
        { label: '处理中', value: (s.fetching || 0) + (s.transcribing || 0) + (s.cleaning || 0) + (s.classifying || 0) + (s.extracting || 0), cls: 'badge-blue' },
      ]
    : [];

  if (stats.loading || creators.loading) return <Spinner />;
  if (stats.error) return <ErrorBox message={stats.error} />;
  if (creators.error) return <ErrorBox message={creators.error} />;

  return (
    <div className="space-y-6">
      <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-6 gap-4">
        {cards.map((c) => (
          <div key={c.label} className="card">
            <div className="text-xs text-slate-400">{c.label}</div>
            <div className="text-2xl font-bold text-white mt-1">{c.value}</div>
          </div>
        ))}
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        <div className="card">
          <div className="flex items-center justify-between mb-4">
            <h3 className="font-semibold text-white">处理统计</h3>
            <button type="button" className="btn btn-ghost text-xs" onClick={stats.reload}>
              <RefreshCw size={14} /> 刷新
            </button>
          </div>
          {s && (
            <div className="space-y-2">
              {[
                { k: 'fetching',      label: '取流' },
                { k: 'transcribing',  label: '转录' },
                { k: 'cleaning',      label: '清洗' },
                { k: 'classifying',   label: '分类' },
                { k: 'extracting',    label: '提取' },
              ].map((row) => (
                <div key={row.k} className="flex items-center justify-between text-sm">
                  <span className="text-slate-400">{row.label}</span>
                  <span className="text-white">{(s as any)[row.k] ?? 0}</span>
                </div>
              ))}
            </div>
          )}
        </div>

        <div className="card">
          <div className="flex items-center gap-2 mb-4">
            <Clock size={16} className="text-slate-400" />
            <h3 className="font-semibold text-white">最近检查的创作号</h3>
          </div>
          {recent.length === 0 ? (
            <p className="text-sm text-slate-500">暂无数据</p>
          ) : (
            <ul className="space-y-2">
              {recent.map((c) => (
                <li key={c.id} className="flex items-center justify-between text-sm">
                  <div className="flex items-center gap-2 min-w-0">
                    <span className="text-white truncate">{c.name}</span>
                    <span className="text-slate-500 text-xs">{c.platform}</span>
                  </div>
                  <span className="text-slate-500 text-xs">{safeDate(c.last_checked)}</span>
                </li>
              ))}
            </ul>
          )}
        </div>
      </div>
    </div>
  );
}

/* ------------------------------------------------------------------ */
/* 2. Creators                                                         */
/* ------------------------------------------------------------------ */

export function Creators() {
  const { data, loading, error, reload } = useAsync<Creator[]>(() => apiClient.get('/api/creators'));
  const creators = data || [];

  const [biliSearch, setBiliSearch] = useState('');
  const [wechatSearch, setWechatSearch] = useState('');
  const [addBili, setAddBili] = useState({ uid: '', name: '' });
  const [addWechat, setAddWechat] = useState({ uid: '', name: '' });
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState('');

  const grouped = useMemo(() => {
    const bili = creators.filter(
      (c) => c.platform === 'bilibili' &&
        (c.name?.toLowerCase().includes(biliSearch.toLowerCase()) ||
          c.uid?.includes(biliSearch)),
    );
    const wechat = creators.filter(
      (c) => c.platform === 'wechat' &&
        (c.name?.toLowerCase().includes(wechatSearch.toLowerCase()) ||
          c.uid?.includes(wechatSearch)),
    );
    return { bili, wechat };
  }, [creators, biliSearch, wechatSearch]);

  const addCreator = async (platform: 'bilibili' | 'wechat', form: { uid: string; name: string }) => {
    if (!form.uid.trim()) return;
    setBusy(true);
    setNotice('');
    try {
      await apiClient.post('/api/creators', {
        platform,
        uid: form.uid.trim(),
        name: form.name.trim() || form.uid.trim(),
        update_strategy: 'latest',
        priority: 'normal',
        content_types: [],
        custom_tags: [],
        enabled: 1,
      });
      setNotice(`已添加 ${platform === 'bilibili' ? 'B站' : '公众号'} 创作号: ${form.name || form.uid}`);
      if (platform === 'bilibili') setAddBili({ uid: '', name: '' });
      else setAddWechat({ uid: '', name: '' });
      reload();
    } catch (e: unknown) {
      setNotice(`添加失败: ${e instanceof Error ? e.message : String(e)}`);
    } finally {
      setBusy(false);
    }
  };

  const removeCreator = async (id: number, name: string) => {
    if (!window.confirm(`确认删除创作号「${name}」？`)) return;
    setBusy(true);
    setNotice('');
    try {
      await apiClient.del(`/api/creators/${id}`);
      setNotice(`已删除: ${name}`);
      reload();
    } catch (e: unknown) {
      setNotice(`删除失败: ${e instanceof Error ? e.message : String(e)}`);
    } finally {
      setBusy(false);
    }
  };

  const checkNew = async (c: Creator) => {
    setBusy(true);
    setNotice('');
    try {
      await apiClient.post(`/api/creators/${c.id}/check`, {});
      setNotice(`已触发检查: ${c.name}`);
      reload();
    } catch (e: unknown) {
      setNotice(`检查失败: ${e instanceof Error ? e.message : String(e)}`);
    } finally {
      setBusy(false);
    }
  };

  const Column = ({
    title,
    platform,
    search,
    setSearch,
    add,
    setAdd,
    list,
  }: {
    title: string;
    platform: 'bilibili' | 'wechat';
    search: string;
    setSearch: (v: string) => void;
    add: { uid: string; name: string };
    setAdd: (v: { uid: string; name: string }) => void;
    list: Creator[];
  }) => (
    <div className="card flex flex-col">
      <h3 className="font-semibold text-white mb-3">{title}</h3>

      <div className="relative mb-3">
        <Search size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-slate-500" />
        <input
          className="w-full pl-8"
          placeholder={`搜索 ${title}...`}
          value={search}
          onChange={(e) => setSearch(e.target.value)}
        />
      </div>

      <div className="flex gap-2 mb-4">
        <input
          className="flex-1"
          placeholder="UID / 公众号ID"
          value={add.uid}
          onChange={(e) => setAdd({ ...add, uid: e.target.value })}
        />
        <input
          className="flex-1"
          placeholder="名称（可选）"
          value={add.name}
          onChange={(e) => setAdd({ ...add, name: e.target.value })}
        />
        <button
          type="button"
          className="btn btn-primary"
          disabled={busy || !add.uid.trim()}
          onClick={() => addCreator(platform, add)}
        >
          <Plus size={14} /> 添加
        </button>
      </div>

      <div className="space-y-2 overflow-y-auto max-h-[60vh]">
        {list.length === 0 ? (
          <p className="text-sm text-slate-500 py-4 text-center">暂无创作号</p>
        ) : (
          list.map((c) => (
            <div key={c.id} className="rounded-lg border border-slate-800 p-3 bg-slate-900/60">
              <div className="flex items-start justify-between gap-2">
                <div className="min-w-0">
                  <div className="flex items-center gap-2">
                    <span className="text-white font-medium truncate">{c.name}</span>
                    <span className="text-xs text-slate-500">{c.uid}</span>
                  </div>
                  <div className="flex items-center gap-1.5 mt-1.5 wrap">
                    <span className="badge badge-blue">{c.update_strategy || '-'}</span>
                    <span className="badge badge-yellow">{c.priority || '-'}</span>
                  </div>
                  <div className="text-xs text-slate-500 mt-1.5">
                    最后检查: {safeDate(c.last_checked)}
                  </div>
                </div>
                <div className="flex flex-col gap-1 shrink-0">
                  <button
                    type="button"
                    className="btn btn-ghost text-xs px-2 py-1"
                    title="检查新内容"
                    disabled={busy}
                    onClick={() => checkNew(c)}
                  >
                    <RefreshCw size={12} />
                  </button>
                  <button
                    type="button"
                    className="btn btn-ghost text-xs px-2 py-1"
                    title="编辑"
                    disabled={busy}
                    onClick={() => setNotice(`编辑功能即将上线 (id=${c.id})`)}
                  >
                    <FileText size={12} />
                  </button>
                  <button
                    type="button"
                    className="btn btn-danger text-xs px-2 py-1"
                    title="删除"
                    disabled={busy}
                    onClick={() => removeCreator(c.id, c.name)}
                  >
                    <Trash2 size={12} />
                  </button>
                </div>
              </div>
            </div>
          ))
        )}
      </div>
    </div>
  );

  if (loading) return <Spinner />;
  if (error) return <ErrorBox message={error} />;

  return (
    <div className="space-y-4">
      {notice && (
        <div className="card text-sm text-slate-300">
          <div className="flex items-center gap-2">
            {notice.includes('失败') ? <XCircle size={14} className="text-red-400" /> : <CheckCircle size={14} className="text-green-400" />}
            <span>{notice}</span>
          </div>
        </div>
      )}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        <Column
          title="B站 bilibili"
          platform="bilibili"
          search={biliSearch}
          setSearch={setBiliSearch}
          add={addBili}
          setAdd={setAddBili}
          list={grouped.bili}
        />
        <Column
          title="公众号 WeChat"
          platform="wechat"
          search={wechatSearch}
          setSearch={setWechatSearch}
          add={addWechat}
          setAdd={setAddWechat}
          list={grouped.wechat}
        />
      </div>
    </div>
  );
}

/* ------------------------------------------------------------------ */
/* 3. ContentList                                                      */
/* ------------------------------------------------------------------ */

export function ContentList() {
  const { data, loading, error, reload } = useAsync<Content[]>(() => apiClient.get('/api/contents'));
  const creatorsHook = useAsync<Creator[]>(() => apiClient.get('/api/creators'), []);

  const [statusFilter, setStatusFilter] = useState('all');
  const [catFilter, setCatFilter] = useState('all');
  const [page, setPage] = useState(1);
  const [actionId, setActionId] = useState<number | null>(null);
  const [notice, setNotice] = useState('');

  const creatorMap = useMemo(() => {
    const m = new Map<number, string>();
    (creatorsHook.data || []).forEach((c) => m.set(c.id, c.name));
    return m;
  }, [creatorsHook.data]);

  const categories = useMemo(() => {
    const set = new Set<string>();
    (data || []).forEach((c) => c.category && set.add(c.category));
    return ['all', ...Array.from(set).sort()];
  }, [data]);

  const filtered = useMemo(() => {
    return (data || []).filter((c) => {
      if (statusFilter !== 'all' && c.status !== statusFilter) return false;
      if (catFilter !== 'all' && c.category !== catFilter) return false;
      return true;
    });
  }, [data, statusFilter, catFilter]);

  const totalPages = Math.max(1, Math.ceil(filtered.length / PAGE_SIZE));
  const safePage = Math.min(page, totalPages);
  const pageItems = filtered.slice((safePage - 1) * PAGE_SIZE, safePage * PAGE_SIZE);

  useEffect(() => {
    setPage(1);
  }, [statusFilter, catFilter]);

  const processOne = async (id: number) => {
    setActionId(id);
    setNotice('');
    try {
      await apiClient.post(`/api/process/${id}`, {});
      setNotice(`已触发处理: #${id}`);
      reload();
    } catch (e: unknown) {
      setNotice(`处理失败: ${e instanceof Error ? e.message : String(e)}`);
    } finally {
      setActionId(null);
    }
  };

  if (loading) return <Spinner />;
  if (error) return <ErrorBox message={error} />;

  return (
    <div className="space-y-4">
      {notice && (
        <div className="card text-sm text-slate-300">
          <div className="flex items-center gap-2">
            {notice.includes('失败') ? <XCircle size={14} className="text-red-400" /> : <CheckCircle size={14} className="text-green-400" />}
            <span>{notice}</span>
          </div>
        </div>
      )}

      <div className="card">
        <div className="flex flex-wrap items-center gap-3 mb-4">
          <div className="flex items-center gap-2">
            <label className="text-xs text-slate-400">状态</label>
            <select value={statusFilter} onChange={(e) => setStatusFilter(e.target.value)}>
              <option value="all">全部</option>
              <option value="pending">pending</option>
              <option value="fetching">fetching</option>
              <option value="transcribing">transcribing</option>
              <option value="cleaning">cleaning</option>
              <option value="classifying">classifying</option>
              <option value="extracting">extracting</option>
              <option value="done">done</option>
              <option value="failed">failed</option>
            </select>
          </div>
          <div className="flex items-center gap-2">
            <label className="text-xs text-slate-400">分类</label>
            <select value={catFilter} onChange={(e) => setCatFilter(e.target.value)}>
              {categories.map((c) => (
                <option key={c} value={c}>{c === 'all' ? '全部' : c}</option>
              ))}
            </select>
          </div>
          <span className="text-xs text-slate-500 ml-auto">共 {filtered.length} 条</span>
        </div>

        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="text-left text-slate-400 border-b border-slate-800">
                <th className="py-2 pr-3">标题</th>
                <th className="py-2 pr-3">平台</th>
                <th className="py-2 pr-3">状态</th>
                <th className="py-2 pr-3">分类</th>
                <th className="py-2 pr-3">UP主</th>
                <th className="py-2 pr-3">时长</th>
                <th className="py-2 pr-3">处理时间</th>
                <th className="py-2 pr-3">操作</th>
              </tr>
            </thead>
            <tbody>
              {pageItems.length === 0 ? (
                <tr>
                  <td colSpan={8} className="py-6 text-center text-slate-500">暂无数据</td>
                </tr>
              ) : (
                pageItems.map((c) => (
                  <tr key={c.id} className="border-b border-slate-800/60 hover:bg-slate-800/30">
                    <td className="py-2 pr-3 max-w-xs truncate" title={c.title}>{c.title || '-'}</td>
                    <td className="py-2 pr-3 text-slate-400">{c.platform}</td>
                    <td className="py-2 pr-3"><StatusBadge status={c.status} /></td>
                    <td className="py-2 pr-3 text-slate-400">{c.category || '-'}</td>
                    <td className="py-2 pr-3 text-slate-400">{creatorMap.get(c.creator_id) || `#${c.creator_id}`}</td>
                    <td className="py-2 pr-3 text-slate-400">{formatDuration(c.duration)}</td>
                    <td className="py-2 pr-3 text-slate-500 text-xs">{safeDate(c.processed_at)}</td>
                    <td className="py-2 pr-3">
                      {(c.status === 'pending' || c.status === 'failed') ? (
                        <button
                          type="button"
                          className="btn btn-primary text-xs px-2 py-1"
                          disabled={actionId === c.id}
                          onClick={() => processOne(c.id)}
                        >
                          {actionId === c.id ? <RefreshCw size={12} className="animate-spin" /> : <Play size={12} />} 处理
                        </button>
                      ) : c.status === 'done' && c.note_path ? (
                        <a
                          href={`obsidian://open?vault=${encodeURIComponent(c.note_path)}`}
                          className="btn btn-ghost text-xs px-2 py-1"
                          target="_blank"
                          rel="noreferrer"
                        >
                          <Eye size={12} /> 查看
                        </a>
                      ) : (
                        <span className="text-slate-600 text-xs">-</span>
                      )}
                    </td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>

        {totalPages > 1 && (
          <div className="flex items-center justify-end gap-2 mt-4 text-sm">
            <button
              type="button"
              className="btn btn-ghost text-xs"
              disabled={safePage <= 1}
              onClick={() => setPage(safePage - 1)}
            >
              上一页
            </button>
            <span className="text-slate-400">
              {safePage} / {totalPages}
            </span>
            <button
              type="button"
              className="btn btn-ghost text-xs"
              disabled={safePage >= totalPages}
              onClick={() => setPage(safePage + 1)}
            >
              下一页
            </button>
          </div>
        )}
      </div>
    </div>
  );
}

/* ------------------------------------------------------------------ */
/* 4. Processing                                                       */
/* ------------------------------------------------------------------ */

export function Processing() {
  const stats = useAsync<ProcessStats>(() => apiClient.get('/api/process/stats'));
  const tasks = useAsync<Task[]>(() => apiClient.get('/api/process/tasks'), []);
  const [retryId, setRetryId] = useState<number | null>(null);
  const [notice, setNotice] = useState('');

  const s = stats.data;
  const taskList = tasks.data || [];

  const statCards: { label: string; value: number; cls: string }[] = s
    ? [
        { label: '总数', value: s.total, cls: 'badge-gray' },
        { label: '待处理', value: s.pending, cls: 'badge-yellow' },
        { label: '取流', value: s.fetching, cls: 'badge-blue' },
        { label: '转录', value: s.transcribing, cls: 'badge-blue' },
        { label: '清洗', value: s.cleaning, cls: 'badge-blue' },
        { label: '分类', value: s.classifying, cls: 'badge-blue' },
        { label: '提取', value: s.extracting, cls: 'badge-blue' },
        { label: '完成', value: s.done, cls: 'badge-green' },
        { label: '失败', value: s.failed, cls: 'badge-red' },
      ]
    : [];

  const retry = async (t: Task) => {
    setRetryId(t.content_id);
    setNotice('');
    try {
      await apiClient.post(`/api/process/${t.content_id}/retry`, {});
      setNotice(`已重试: #${t.content_id}`);
      stats.reload();
      tasks.reload();
    } catch (e: unknown) {
      setNotice(`重试失败: ${e instanceof Error ? e.message : String(e)}`);
    } finally {
      setRetryId(null);
    }
  };

  return (
    <div className="space-y-4">
      {notice && (
        <div className="card text-sm text-slate-300">
          <div className="flex items-center gap-2">
            {notice.includes('失败') ? <XCircle size={14} className="text-red-400" /> : <CheckCircle size={14} className="text-green-400" />}
            <span>{notice}</span>
          </div>
        </div>
      )}

      {stats.loading ? (
        <Spinner />
      ) : stats.error ? (
        <ErrorBox message={stats.error} />
      ) : (
        <div className="grid grid-cols-3 md:grid-cols-5 lg:grid-cols-9 gap-3">
          {statCards.map((c) => (
            <div key={c.label} className="card text-center">
              <div className="text-xs text-slate-400 mb-1">{c.label}</div>
              <div className={`text-2xl font-bold ${c.cls === 'badge-green' ? 'text-green-400' : c.cls === 'badge-red' ? 'text-red-400' : c.cls === 'badge-yellow' ? 'text-yellow-400' : c.cls === 'badge-blue' ? 'text-blue-400' : 'text-white'}`}>
                {c.value}
              </div>
            </div>
          ))}
        </div>
      )}

      <div className="card">
        <div className="flex items-center justify-between mb-4">
          <h3 className="font-semibold text-white">任务队列</h3>
          <button type="button" className="btn btn-ghost text-xs" onClick={tasks.reload}>
            <RefreshCw size={14} /> 刷新
          </button>
        </div>

        {tasks.loading ? (
          <Spinner label="加载任务..." />
        ) : tasks.error ? (
          <ErrorBox message={tasks.error} />
        ) : taskList.length === 0 ? (
          <p className="text-sm text-slate-500 py-4 text-center">队列为空</p>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="text-left text-slate-400 border-b border-slate-800">
                  <th className="py-2 pr-3">Content ID</th>
                  <th className="py-2 pr-3">任务类型</th>
                  <th className="py-2 pr-3">状态</th>
                  <th className="py-2 pr-3">开始</th>
                  <th className="py-2 pr-3">结束</th>
                  <th className="py-2 pr-3">错误</th>
                  <th className="py-2 pr-3">操作</th>
                </tr>
              </thead>
              <tbody>
                {taskList.map((t, i) => (
                  <tr key={t.id ?? i} className="border-b border-slate-800/60 hover:bg-slate-800/30">
                    <td className="py-2 pr-3">#{t.content_id}</td>
                    <td className="py-2 pr-3 text-slate-300">{t.task_type}</td>
                    <td className="py-2 pr-3"><StatusBadge status={t.status} /></td>
                    <td className="py-2 pr-3 text-slate-500 text-xs">{safeDate(t.started_at)}</td>
                    <td className="py-2 pr-3 text-slate-500 text-xs">{safeDate(t.finished_at)}</td>
                    <td className="py-2 pr-3 text-red-400 text-xs max-w-xs truncate" title={t.error}>{t.error || '-'}</td>
                    <td className="py-2 pr-3">
                      {t.status === 'failed' && (
                        <button
                          type="button"
                          className="btn btn-primary text-xs px-2 py-1"
                          disabled={retryId === t.content_id}
                          onClick={() => retry(t)}
                        >
                          {retryId === t.content_id ? <RefreshCw size={12} className="animate-spin" /> : <RefreshCw size={12} />} 重试
                        </button>
                      )}
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

/* ------------------------------------------------------------------ */
/* 5. Notes                                                            */
/* ------------------------------------------------------------------ */

export function Notes() {
  const { data, loading, error, reload } = useAsync<Note[]>(() => apiClient.get('/api/notes'));
  const [query, setQuery] = useState('');
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState('');

  const grouped = useMemo(() => {
    const q = query.trim().toLowerCase();
    const filtered = (data || []).filter((n) => {
      if (!q) return true;
      return (
        n.title?.toLowerCase().includes(q) ||
        n.up?.toLowerCase().includes(q) ||
        n.tags?.some((t) => t.toLowerCase().includes(q))
      );
    });
    const map = new Map<string, Note[]>();
    filtered.forEach((n) => {
      const cat = n.category || '未分类';
      if (!map.has(cat)) map.set(cat, []);
      map.get(cat)!.push(n);
    });
    return Array.from(map.entries()).sort((a, b) => a[0].localeCompare(b[0]));
  }, [data, query]);

  const regenMoc = async () => {
    setBusy(true);
    setNotice('');
    try {
      await apiClient.post('/api/notes/moc', {});
      setNotice('MOC 重新生成成功');
      reload();
    } catch (e: unknown) {
      setNotice(`生成失败: ${e instanceof Error ? e.message : String(e)}`);
    } finally {
      setBusy(false);
    }
  };

  if (loading) return <Spinner />;
  if (error) return <ErrorBox message={error} />;

  return (
    <div className="space-y-4">
      {notice && (
        <div className="card text-sm text-slate-300">
          <div className="flex items-center gap-2">
            {notice.includes('失败') ? <XCircle size={14} className="text-red-400" /> : <CheckCircle size={14} className="text-green-400" />}
            <span>{notice}</span>
          </div>
        </div>
      )}

      <div className="card flex flex-wrap items-center gap-3">
        <div className="relative flex-1 min-w-48">
          <Search size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-slate-500" />
          <input
            className="w-full pl-8"
            placeholder="搜索笔记标题 / UP主 / 标签..."
            value={query}
            onChange={(e) => setQuery(e.target.value)}
          />
        </div>
        <button
          type="button"
          className="btn btn-primary"
          disabled={busy}
          onClick={regenMoc}
        >
          {busy ? <RefreshCw size={14} className="animate-spin" /> : <FolderTree size={14} />} 重新生成 MOC
        </button>
      </div>

      {grouped.length === 0 ? (
        <div className="card text-center text-slate-500 text-sm py-8">暂无笔记</div>
      ) : (
        grouped.map(([cat, notes]) => (
          <div key={cat} className="card">
            <div className="flex items-center gap-2 mb-3">
              <Layers size={16} className="text-blue-400" />
              <h3 className="font-semibold text-white">{cat}</h3>
              <span className="text-xs text-slate-500">({notes.length})</span>
            </div>
            <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-3">
              {notes.map((n, i) => (
                <div key={`${n.path}-${i}`} className="rounded-lg border border-slate-800 p-3 bg-slate-900/60 hover:border-slate-700">
                  <div className="flex items-start gap-2">
                    <FileText size={14} className="text-slate-500 mt-0.5 shrink-0" />
                    <div className="min-w-0 flex-1">
                      <div className="text-white text-sm truncate" title={n.title}>{n.title || '(无标题)'}</div>
                      <div className="text-xs text-slate-500 mt-1">UP: {n.up || '-'}</div>
                      <div className="flex flex-wrap gap-1 mt-2">
                        {n.tags?.map((t) => (
                          <span key={t} className="badge badge-gray text-xs">
                            <Tag size={10} className="inline mr-1" />{t}
                          </span>
                        ))}
                        {(!n.tags || n.tags.length === 0) && (
                          <span className="text-xs text-slate-600">无标签</span>
                        )}
                      </div>
                      {n.path && (
                        <a
                          href={`obsidian://open?path=${encodeURIComponent(n.path)}`}
                          className="text-xs text-blue-400 hover:underline mt-2 inline-block"
                          target="_blank"
                          rel="noreferrer"
                        >
                          在 Obsidian 中打开
                        </a>
                      )}
                    </div>
                  </div>
                </div>
              ))}
            </div>
          </div>
        ))
      )}
    </div>
  );
}

/* ------------------------------------------------------------------ */
/* 6. Review                                                           */
/* ------------------------------------------------------------------ */

export function Review() {
  const { data, loading, error, reload } = useAsync<any>(() => apiClient.get('/api/review'));
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState('');

  const summary = data || {};
  const reviewed = Number(summary.reviewed ?? 0);
  const pending = Number(summary.pending ?? 0);
  const totalNotes = reviewed + pending;
  const reportPath: string = summary.last_report || summary.report_path || '';
  const lastRun: string = summary.last_run || summary.updated_at || '';

  const triggerReview = async () => {
    if (!window.confirm('启动自动审查？这可能需要较长时间。')) return;
    setBusy(true);
    setNotice('');
    try {
      const r = await apiClient.post<any>('/api/review?mode=auto', {});
      setNotice(`审查已完成: ${r?.reviewed ?? ''} 篇已审 / ${r?.pending ?? ''} 篇待审`);
      reload();
    } catch (e: unknown) {
      setNotice(`审查失败: ${e instanceof Error ? e.message : String(e)}`);
    } finally {
      setBusy(false);
    }
  };

  if (loading) return <Spinner />;
  if (error) return <ErrorBox message={error} />;

  return (
    <div className="space-y-4">
      {notice && (
        <div className="card text-sm text-slate-300">
          <div className="flex items-center gap-2">
            {notice.includes('失败') ? <XCircle size={14} className="text-red-400" /> : <CheckCircle size={14} className="text-green-400" />}
            <span>{notice}</span>
          </div>
        </div>
      )}

      <div className="card flex items-center justify-between">
        <div>
          <h3 className="font-semibold text-white mb-1">自动审查</h3>
          <p className="text-xs text-slate-400">扫描已生成笔记，纠正拼写、补全事实、提取待验证声明。</p>
        </div>
        <button
          type="button"
          className="btn btn-primary"
          disabled={busy}
          onClick={triggerReview}
        >
          {busy ? <RefreshCw size={14} className="animate-spin" /> : <Play size={14} />} 启动审查
        </button>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
        <div className="card text-center">
          <div className="text-xs text-slate-400">已审查</div>
          <div className="text-3xl font-bold text-green-400 mt-1">{reviewed}</div>
        </div>
        <div className="card text-center">
          <div className="text-xs text-slate-400">待审查</div>
          <div className="text-3xl font-bold text-yellow-400 mt-1">{pending}</div>
        </div>
        <div className="card text-center">
          <div className="text-xs text-slate-400">笔记总数</div>
          <div className="text-3xl font-bold text-white mt-1">{totalNotes}</div>
        </div>
      </div>

      <div className="card">
        <h3 className="font-semibold text-white mb-3">最近审查报告</h3>
        {reportPath ? (
          <div className="space-y-2 text-sm">
            <div className="flex items-center gap-2 text-slate-300">
              <FileText size={14} className="text-slate-400" />
              <span className="font-mono break-all">{reportPath}</span>
            </div>
            {lastRun && (
              <div className="flex items-center gap-2 text-slate-500 text-xs">
                <Clock size={12} />
                <span>{safeDate(lastRun)}</span>
              </div>
            )}
            <a
              href={`obsidian://open?path=${encodeURIComponent(reportPath)}`}
              className="text-blue-400 hover:underline text-xs"
              target="_blank"
              rel="noreferrer"
            >
              在 Obsidian 中打开
            </a>
          </div>
        ) : (
          <p className="text-sm text-slate-500">暂无审查报告，请先执行审查。</p>
        )}
      </div>
    </div>
  );
}

/* ------------------------------------------------------------------ */
/* 7. Claims                                                           */
/* ------------------------------------------------------------------ */

export function Claims() {
  const { data, loading, error, reload } = useAsync<PendingClaim[]>(() => apiClient.get('/api/review/claims'));
  const [corrections, setCorrections] = useState<Record<number, string>>({});
  const [busyId, setBusyId] = useState<number | null>(null);
  const [notice, setNotice] = useState('');

  const claims = data || [];

  const resolve = async (claim: PendingClaim, action: 'confirm' | 'correct' | 'remove', correction?: string) => {
    if (action === 'correct' && !correction?.trim()) {
      setNotice('请输入修正文本');
      return;
    }
    setBusyId(claim.id);
    setNotice('');
    try {
      await apiClient.post('/api/review/resolve', {
        claim_id: claim.id,
        action,
        correction: action === 'correct' ? correction?.trim() : undefined,
      });
      setNotice(`声明 #${claim.id} 已处理: ${action}`);
      setCorrections((p) => {
        const n = { ...p };
        delete n[claim.id];
        return n;
      });
      reload();
    } catch (e: unknown) {
      setNotice(`处理失败: ${e instanceof Error ? e.message : String(e)}`);
    } finally {
      setBusyId(null);
    }
  };

  if (loading) return <Spinner />;
  if (error) return <ErrorBox message={error} />;

  return (
    <div className="space-y-4">
      {notice && (
        <div className="card text-sm text-slate-300">
          <div className="flex items-center gap-2">
            {notice.includes('失败') || notice.includes('请输入') ? <XCircle size={14} className="text-red-400" /> : <CheckCircle size={14} className="text-green-400" />}
            <span>{notice}</span>
          </div>
        </div>
      )}

      <div className="flex items-center justify-between">
        <span className="text-sm text-slate-400">共 {claims.length} 条待验证声明</span>
        <button type="button" className="btn btn-ghost text-xs" onClick={reload}>
          <RefreshCw size={14} /> 刷新
        </button>
      </div>

      {claims.length === 0 ? (
        <div className="card text-center text-slate-500 text-sm py-8">暂无待验证声明</div>
      ) : (
        claims.map((c) => (
          <div key={c.id} className="card">
            <div className="flex items-start justify-between gap-4">
              <div className="flex-1 min-w-0">
                <div className="flex items-center gap-2 mb-2">
                  <span className="badge badge-blue">{c.claim_type || 'claim'}</span>
                  <StatusBadge status={c.status} />
                  <span className="text-xs text-slate-500">#{c.id}</span>
                </div>
                <p className="text-slate-200 text-sm mb-2">{c.claim}</p>
                <div className="text-xs text-slate-500">
                  来源: {c.title || `content #${c.content_id}`}
                  {c.category && <span className="ml-2">| 分类: {c.category}</span>}
                </div>
              </div>
            </div>

            <div className="mt-3 pt-3 border-t border-slate-800 space-y-2">
              <div className="flex items-center gap-2">
                <input
                  className="flex-1"
                  placeholder="输入修正文本..."
                  value={corrections[c.id] || ''}
                  onChange={(e) => setCorrections((p) => ({ ...p, [c.id]: e.target.value }))}
                />
              </div>
              <div className="flex flex-wrap items-center gap-2">
                <button
                  type="button"
                  className="btn btn-success text-xs"
                  disabled={busyId === c.id}
                  onClick={() => resolve(c, 'confirm')}
                >
                  <CheckCircle size={12} /> 确认
                </button>
                <button
                  type="button"
                  className="btn btn-primary text-xs"
                  disabled={busyId === c.id}
                  onClick={() => resolve(c, 'correct', corrections[c.id])}
                >
                  <Upload size={12} /> 修正
                </button>
                <button
                  type="button"
                  className="btn btn-danger text-xs"
                  disabled={busyId === c.id}
                  onClick={() => {
                    if (window.confirm('确认移除此声明？')) resolve(c, 'remove');
                  }}
                >
                  <Trash2 size={12} /> 移除
                </button>
              </div>
            </div>
          </div>
        ))
      )}
    </div>
  );
}

/* ------------------------------------------------------------------ */
/* 8. Settings                                                         */
/* ------------------------------------------------------------------ */

const DEFAULT_SETTINGS: SettingsType = {
  obsidian_vault: '',
  ai_api_base: '',
  ai_text_model: '',
  ai_vision_model: '',
  temperature: 0.7,
  max_tokens: 4096,
  whisper_mode: 'local',
  whisper_model: 'medium',
  whisper_language: 'zh',
  bilibili_sessdata: '',
  wechat_method: 'rss',
  schedule_check_time: '09:00',
  ad_filter_prompt: '',
  domain_taxonomy: {},
};

export function Settings() {
  const { data, loading, error, reload } = useAsync<SettingsType>(() => apiClient.get('/api/settings'));
  const [form, setForm] = useState<SettingsType>(DEFAULT_SETTINGS);
  const [taxonomyText, setTaxonomyText] = useState('{}');
  const [taxonomyError, setTaxonomyError] = useState('');
  const [saving, setSaving] = useState(false);
  const [notice, setNotice] = useState('');
  const [testingVault, setTestingVault] = useState(false);
  const [vaultResult, setVaultResult] = useState('');

  useEffect(() => {
    if (data) {
      setForm({ ...DEFAULT_SETTINGS, ...data });
      try {
        setTaxonomyText(JSON.stringify(data.domain_taxonomy ?? {}, null, 2));
      } catch {
        setTaxonomyText('{}');
      }
    }
  }, [data]);

  const update = (key: string, value: unknown) => {
    setForm((p) => ({ ...p, [key]: value }));
  };

  const save = async () => {
    setSaving(true);
    setNotice('');
    setTaxonomyError('');
    let taxonomy: unknown = form.domain_taxonomy;
    try {
      taxonomy = JSON.parse(taxonomyText);
    } catch (e: unknown) {
      setTaxonomyError('Domain taxonomy JSON 解析失败');
      setSaving(false);
      return;
    }
    const payload: SettingsType = { ...form, domain_taxonomy: taxonomy };
    try {
      await apiClient.put('/api/settings', payload);
      setNotice('保存成功');
      setTimeout(() => setNotice(''), 3000);
      reload();
    } catch (e: unknown) {
      setNotice(`保存失败: ${e instanceof Error ? e.message : String(e)}`);
    } finally {
      setSaving(false);
    }
  };

  const testVault = async () => {
    setTestingVault(true);
    setVaultResult('');
    try {
      const r = await apiClient.post<{ ok: boolean; message?: string }>('/api/settings/test-vault', {
        path: form.obsidian_vault,
      });
      setVaultResult(r.ok ? '✓ 连接成功' : `✗ ${r.message || '失败'}`);
    } catch (e: unknown) {
      setVaultResult(`✗ ${e instanceof Error ? e.message : String(e)}`);
    } finally {
      setTestingVault(false);
    }
  };

  if (loading) return <Spinner />;
  if (error) return <ErrorBox message={error} />;

  const Section = ({ title, children }: { title: string; children: React.ReactNode }) => (
    <div className="card">
      <h3 className="font-semibold text-white mb-4">{title}</h3>
      {children}
    </div>
  );

  const Field = ({ label, children }: { label: string; children: React.ReactNode }) => (
    <div className="mb-3">
      <label className="block text-xs text-slate-400 mb-1">{label}</label>
      {children}
    </div>
  );

  return (
    <div className="space-y-4 max-w-4xl">
      {notice && (
        <div className="card text-sm text-slate-300">
          <div className="flex items-center gap-2">
            {notice.includes('失败') ? <XCircle size={14} className="text-red-400" /> : <CheckCircle size={14} className="text-green-400" />}
            <span>{notice}</span>
          </div>
        </div>
      )}

      <Section title="Obsidian Vault">
        <Field label="Vault 路径">
          <div className="flex gap-2">
            <input
              className="flex-1"
              value={form.obsidian_vault || ''}
              onChange={(e) => update('obsidian_vault', e.target.value)}
              placeholder="/path/to/vault"
            />
            <button
              type="button"
              className="btn btn-ghost text-xs whitespace-nowrap"
              disabled={testingVault}
              onClick={testVault}
            >
              {testingVault ? <RefreshCw size={14} className="animate-spin" /> : <RefreshCw size={14} />} 测试
            </button>
          </div>
          {vaultResult && (
            <p className={`text-xs mt-1 ${vaultResult.startsWith('✓') ? 'text-green-400' : 'text-red-400'}`}>
              {vaultResult}
            </p>
          )}
        </Field>
      </Section>

      <Section title="AI 配置">
        <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
          <Field label="API Base">
            <input
              className="w-full"
              value={form.ai_api_base || ''}
              onChange={(e) => update('ai_api_base', e.target.value)}
              placeholder="https://api.openai.com/v1"
            />
          </Field>
          <Field label="文本模型">
            <input
              className="w-full"
              value={form.ai_text_model || ''}
              onChange={(e) => update('ai_text_model', e.target.value)}
              placeholder="gpt-4o"
            />
          </Field>
          <Field label="视觉模型">
            <input
              className="w-full"
              value={form.ai_vision_model || ''}
              onChange={(e) => update('ai_vision_model', e.target.value)}
              placeholder="gpt-4o"
            />
          </Field>
          <Field label="Temperature">
            <input
              type="number"
              step="0.1"
              min="0"
              max="2"
              className="w-full"
              value={form.temperature ?? 0.7}
              onChange={(e) => update('temperature', parseFloat(e.target.value))}
            />
          </Field>
          <Field label="Max Tokens">
            <input
              type="number"
              className="w-full"
              value={form.max_tokens ?? 4096}
              onChange={(e) => update('max_tokens', parseInt(e.target.value, 10))}
            />
          </Field>
        </div>
      </Section>

      <Section title="Whisper 配置">
        <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
          <Field label="模式">
            <select
              className="w-full"
              value={form.whisper_mode || 'local'}
              onChange={(e) => update('whisper_mode', e.target.value)}
            >
              <option value="local">本地</option>
              <option value="api">API</option>
              <option value="cloud">云端</option>
            </select>
          </Field>
          <Field label="模型大小">
            <select
              className="w-full"
              value={form.whisper_model || 'medium'}
              onChange={(e) => update('whisper_model', e.target.value)}
            >
              <option value="tiny">tiny</option>
              <option value="base">base</option>
              <option value="small">small</option>
              <option value="medium">medium</option>
              <option value="large">large</option>
              <option value="large-v2">large-v2</option>
              <option value="large-v3">large-v3</option>
            </select>
          </Field>
          <Field label="语言">
            <select
              className="w-full"
              value={form.whisper_language || 'zh'}
              onChange={(e) => update('whisper_language', e.target.value)}
            >
              <option value="zh">中文</option>
              <option value="en">English</option>
              <option value="ja">日本語</option>
              <option value="auto">自动检测</option>
            </select>
          </Field>
        </div>
      </Section>

      <Section title="平台凭据">
        <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
          <Field label="B站 SESSDATA">
            <input
              type="password"
              className="w-full"
              value={form.bilibili_sessdata || ''}
              onChange={(e) => update('bilibili_sessdata', e.target.value)}
              placeholder="SESSDATA cookie"
            />
          </Field>
          <Field label="公众号采集方式">
            <select
              className="w-full"
              value={form.wechat_method || 'rss'}
              onChange={(e) => update('wechat_method', e.target.value)}
            >
              <option value="rss">RSS</option>
              <option value="api">API</option>
              <option value="manual">手动</option>
            </select>
          </Field>
        </div>
      </Section>

      <Section title="调度配置">
        <Field label="每日检查时间">
          <input
            type="time"
            className="w-full md:w-48"
            value={form.schedule_check_time || '09:00'}
            onChange={(e) => update('schedule_check_time', e.target.value)}
          />
        </Field>
      </Section>

      <Section title="广告过滤提示词">
        <Field label="Prompt">
          <textarea
            className="w-full font-mono text-xs"
            rows={4}
            value={form.ad_filter_prompt || ''}
            onChange={(e) => update('ad_filter_prompt', e.target.value)}
            placeholder="识别并标记视频/文章中的广告内容..."
          />
        </Field>
      </Section>

      <Section title="领域分类法 (JSON)">
        <Field label="Taxonomy">
          <textarea
            className="w-full font-mono text-xs"
            rows={10}
            value={taxonomyText}
            onChange={(e) => setTaxonomyText(e.target.value)}
          />
          {taxonomyError && <p className="text-xs text-red-400 mt-1">{taxonomyError}</p>}
        </Field>
      </Section>

      <div className="flex items-center gap-3">
        <button
          type="button"
          className="btn btn-primary"
          disabled={saving}
          onClick={save}
        >
          {saving ? <RefreshCw size={14} className="animate-spin" /> : <Save size={14} />} 保存设置
        </button>
        <button
          type="button"
          className="btn btn-ghost"
          onClick={reload}
        >
          重置
        </button>
      </div>
    </div>
  );
}
