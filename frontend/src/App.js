import React, { useState, useEffect, useCallback } from 'react';
import axios from 'axios';
import {
  LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, Legend
} from 'recharts';
import {
  Search, RefreshCw, Trash2, TrendingUp, TrendingDown, ShoppingCart,
  Star, AlertCircle, CheckCircle, Clock, ExternalLink, Plus, BarChart2,
  Package, DollarSign, Award, Activity
} from 'lucide-react';

const API = 'http://localhost:8001/api';

// ── helpers ──────────────────────────────────────────────────────────────────
const fmt = (v, cur = '£') =>
  v != null ? `${cur}${parseFloat(v).toFixed(2)}` : 'N/A';

const statusColor = (s) =>
  s === 'success' ? '#10b981' : s === 'blocked' ? '#f59e0b' : '#ef4444';

// ── small components ──────────────────────────────────────────────────────────
const Badge = ({ children, color = '#6366f1' }) => (
  <span style={{
    background: color + '22', color, border: `1px solid ${color}44`,
    padding: '2px 10px', borderRadius: 20, fontSize: 11, fontWeight: 600
  }}>{children}</span>
);

const StatCard = ({ icon: Icon, label, value, sub, color }) => (
  <div style={{
    background: 'linear-gradient(135deg,' + color + '22,' + color + '11)',
    border: `1px solid ${color}33`, borderRadius: 16, padding: '20px 24px',
    display: 'flex', alignItems: 'center', gap: 16
  }}>
    <div style={{
      background: color + '22', borderRadius: 12, padding: 12,
      display: 'flex', alignItems: 'center', justifyContent: 'center'
    }}>
      <Icon size={24} color={color} />
    </div>
    <div>
      <div style={{ color: '#94a3b8', fontSize: 12, fontWeight: 500 }}>{label}</div>
      <div style={{ color: '#f1f5f9', fontSize: 24, fontWeight: 800, lineHeight: 1.2 }}>{value}</div>
      {sub && <div style={{ color: '#64748b', fontSize: 11, marginTop: 2 }}>{sub}</div>}
    </div>
  </div>
);

// ── main App ──────────────────────────────────────────────────────────────────
export default function App() {
  const [asin, setAsin] = useState('B01ARH3Q5G');
  const [marketplace, setMarketplace] = useState('amazon.co.uk');
  const [loading, setLoading] = useState(false);
  const [tracked, setTracked] = useState([]);
  const [selected, setSelected] = useState(null);
  const [history, setHistory] = useState([]);
  const [stats, setStats] = useState(null);
  const [error, setError] = useState('');
  const [lastUpdated, setLastUpdated] = useState(null);
  const [activeTab, setActiveTab] = useState('tracker');

  const loadTracked = useCallback(async () => {
    try {
      const [t, s] = await Promise.all([
        axios.get(`${API}/buybox/tracked`),
        axios.get(`${API}/buybox/stats`)
      ]);
      setTracked(t.data.asins || []);
      setStats(s.data);
      setLastUpdated(new Date());
    } catch (_) {}
  }, []);

  useEffect(() => { loadTracked(); }, [loadTracked]);

  const loadHistory = async (asinCode) => {
    try {
      const r = await axios.get(`${API}/buybox/history/${asinCode}`);
      setHistory(r.data.history || []);
    } catch (_) { setHistory([]); }
  };

  const selectProduct = (item) => {
    setSelected(item);
    loadHistory(item.asin);
    setActiveTab('detail');
  };

  const lookup = async () => {
    if (!asin.trim()) return;
    setLoading(true);
    setError('');
    try {
      const r = await axios.post(`${API}/buybox/lookup`, {
        asin: asin.trim().toUpperCase(),
        marketplace
      });
      await loadTracked();
      selectProduct(r.data);
    } catch (e) {
      setError(e.response?.data?.detail || 'Failed to fetch. Is the backend running?');
    } finally {
      setLoading(false);
    }
  };

  const refresh = async (item) => {
    setLoading(true);
    setError('');
    try {
      const r = await axios.post(`${API}/buybox/lookup`, {
        asin: item.asin,
        marketplace: item.marketplace || marketplace
      });
      await loadTracked();
      if (selected?.asin === item.asin) {
        setSelected(r.data);
        loadHistory(item.asin);
      }
    } catch (e) {
      setError('Refresh failed');
    } finally {
      setLoading(false);
    }
  };

  const remove = async (asinCode) => {
    try {
      await axios.delete(`${API}/buybox/tracked/${asinCode}`);
      if (selected?.asin === asinCode) { setSelected(null); setHistory([]); setActiveTab('tracker'); }
      await loadTracked();
    } catch (_) {}
  };

  const handleKey = (e) => { if (e.key === 'Enter') lookup(); };

  // chart data
  const chartData = history.map(h => ({
    time: new Date(h.timestamp).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }),
    price: h.price,
    seller: h.seller
  }));

  // ── render ────────────────────────────────────────────────────────────────
  return (
    <div style={{ minHeight: '100vh', background: '#0f172a', color: '#f1f5f9', fontFamily: 'Inter,sans-serif' }}>

      {/* Header */}
      <header style={{
        background: 'linear-gradient(135deg,#1e3a5f,#1e293b)',
        borderBottom: '1px solid #1e3a5f',
        padding: '0 32px',
        display: 'flex', alignItems: 'center', justifyContent: 'space-between',
        height: 64, position: 'sticky', top: 0, zIndex: 100
      }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
          <div style={{
            background: 'linear-gradient(135deg,#f59e0b,#ef4444)',
            borderRadius: 10, padding: '6px 10px', fontWeight: 800, fontSize: 18
          }}>📦</div>
          <div>
            <div style={{ fontWeight: 800, fontSize: 18, color: '#f1f5f9' }}>Amazon Buybox Tracker</div>
            <div style={{ fontSize: 11, color: '#64748b' }}>Real-time price & seller intelligence</div>
          </div>
        </div>
        <div style={{ display: 'flex', alignItems: 'center', gap: 16 }}>
          {lastUpdated && (
            <div style={{ fontSize: 12, color: '#64748b', display: 'flex', alignItems: 'center', gap: 4 }}>
              <Clock size={12} /> Updated {lastUpdated.toLocaleTimeString()}
            </div>
          )}
          <div style={{
            display: 'flex', alignItems: 'center', gap: 6,
            background: '#10b98122', border: '1px solid #10b98133',
            borderRadius: 20, padding: '4px 12px', fontSize: 12, color: '#10b981'
          }}>
            <span style={{ width: 6, height: 6, background: '#10b981', borderRadius: '50%', display: 'inline-block', animation: 'pulse 2s infinite' }} />
            Live Tracker
          </div>
        </div>
      </header>

      <div style={{ maxWidth: 1400, margin: '0 auto', padding: '24px 32px' }}>

        {/* Stats Row */}
        {stats && (
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4,1fr)', gap: 16, marginBottom: 24 }}>
            <StatCard icon={Package} label="Tracked ASINs" value={stats.total_tracked} sub="Active monitoring" color="#6366f1" />
            <StatCard icon={Award} label="Amazon Wins" value={stats.amazon_wins} sub="Buybox held by Amazon" color="#f59e0b" />
            <StatCard icon={ShoppingCart} label="3rd Party Wins" value={stats.third_party_wins} sub="Buybox held by sellers" color="#10b981" />
            <StatCard icon={DollarSign} label="Avg Buybox Price" value={fmt(stats.avg_buybox_price)} sub="Across tracked ASINs" color="#8b5cf6" />
          </div>
        )}

        {/* Search Bar */}
        <div style={{
          background: '#1e293b', border: '1px solid #334155', borderRadius: 16,
          padding: '20px 24px', marginBottom: 24
        }}>
          <div style={{ fontSize: 13, color: '#94a3b8', marginBottom: 12, fontWeight: 600 }}>
            🔍 Look up Amazon ASIN
          </div>
          <div style={{ display: 'flex', gap: 12, flexWrap: 'wrap' }}>
            <input
              value={asin}
              onChange={e => setAsin(e.target.value)}
              onKeyDown={handleKey}
              placeholder="Enter ASIN (e.g. B01ARH3Q5G)"
              style={{
                flex: 2, minWidth: 200, padding: '12px 16px', borderRadius: 10,
                border: '1px solid #334155', background: '#0f172a', color: '#f1f5f9',
                fontSize: 15, fontWeight: 600, outline: 'none'
              }}
            />
            <select
              value={marketplace}
              onChange={e => setMarketplace(e.target.value)}
              style={{
                flex: 1, minWidth: 160, padding: '12px 16px', borderRadius: 10,
                border: '1px solid #334155', background: '#0f172a', color: '#f1f5f9',
                fontSize: 14, outline: 'none'
              }}
            >
              <option value="amazon.co.uk">🇬🇧 Amazon UK</option>
              <option value="amazon.com">🇺🇸 Amazon US</option>
              <option value="amazon.de">🇩🇪 Amazon DE</option>
              <option value="amazon.fr">🇫🇷 Amazon FR</option>
              <option value="amazon.ca">🇨🇦 Amazon CA</option>
              <option value="amazon.com.au">🇦🇺 Amazon AU</option>
            </select>
            <button
              onClick={lookup}
              disabled={loading}
              style={{
                padding: '12px 28px', borderRadius: 10, border: 'none', cursor: loading ? 'not-allowed' : 'pointer',
                background: loading ? '#334155' : 'linear-gradient(135deg,#f59e0b,#ef4444)',
                color: '#fff', fontWeight: 700, fontSize: 14,
                display: 'flex', alignItems: 'center', gap: 8
              }}
            >
              {loading ? <><RefreshCw size={16} style={{ animation: 'spin 1s linear infinite' }} /> Fetching...</> : <><Search size={16} /> Fetch Buybox</>}
            </button>
          </div>
          {error && (
            <div style={{
              marginTop: 12, background: '#ef444422', border: '1px solid #ef444444',
              borderRadius: 8, padding: '10px 14px', color: '#ef4444', fontSize: 13,
              display: 'flex', alignItems: 'center', gap: 8
            }}>
              <AlertCircle size={14} /> {error}
            </div>
          )}
        </div>

        {/* Main content */}
        <div style={{ display: 'grid', gridTemplateColumns: selected ? '380px 1fr' : '1fr', gap: 24 }}>

          {/* Tracked List */}
          <div style={{ background: '#1e293b', border: '1px solid #334155', borderRadius: 16, overflow: 'hidden' }}>
            <div style={{
              padding: '16px 20px', borderBottom: '1px solid #334155',
              display: 'flex', alignItems: 'center', justifyContent: 'space-between'
            }}>
              <div style={{ fontWeight: 700, fontSize: 15 }}>📋 Tracked ASINs ({tracked.length})</div>
              <button onClick={loadTracked} style={{
                background: '#334155', border: 'none', color: '#94a3b8', borderRadius: 8,
                padding: '6px 10px', cursor: 'pointer', display: 'flex', alignItems: 'center', gap: 4, fontSize: 12
              }}>
                <RefreshCw size={12} /> Refresh All
              </button>
            </div>

            {tracked.length === 0 ? (
              <div style={{ padding: 40, textAlign: 'center', color: '#475569' }}>
                <Package size={40} style={{ opacity: 0.3, marginBottom: 12 }} />
                <div style={{ fontSize: 14 }}>No ASINs tracked yet.</div>
                <div style={{ fontSize: 12, marginTop: 4 }}>Enter an ASIN above to start tracking.</div>
              </div>
            ) : (
              <div style={{ maxHeight: 600, overflowY: 'auto' }}>
                {tracked.map(item => (
                  <div
                    key={item.asin}
                    onClick={() => selectProduct(item)}
                    style={{
                      padding: '14px 20px',
                      borderBottom: '1px solid #1e293b',
                      cursor: 'pointer',
                      background: selected?.asin === item.asin ? '#0f172a' : 'transparent',
                      borderLeft: selected?.asin === item.asin ? '3px solid #f59e0b' : '3px solid transparent',
                      transition: 'all 0.15s'
                    }}
                  >
                    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start' }}>
                      <div style={{ flex: 1, minWidth: 0 }}>
                        <div style={{ fontWeight: 700, fontSize: 12, color: '#f59e0b', marginBottom: 2 }}>
                          {item.asin}
                        </div>
                        <div style={{
                          fontSize: 12, color: '#94a3b8',
                          overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap',
                          maxWidth: 260
                        }}>
                          {item.title || 'Loading...'}
                        </div>
                        <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginTop: 6 }}>
                          <span style={{ fontSize: 16, fontWeight: 800, color: '#10b981' }}>
                            {fmt(item.buybox_price)}
                          </span>
                          <Badge color={item.is_amazon_seller ? '#f59e0b' : '#6366f1'}>
                            {item.buybox_seller || 'Unknown'}
                          </Badge>
                        </div>
                      </div>
                      <div style={{ display: 'flex', gap: 6, marginLeft: 8 }}>
                        <button
                          onClick={e => { e.stopPropagation(); refresh(item); }}
                          style={{ background: '#334155', border: 'none', color: '#94a3b8', borderRadius: 6, padding: '4px 6px', cursor: 'pointer' }}
                          title="Refresh"
                        >
                          <RefreshCw size={12} />
                        </button>
                        <button
                          onClick={e => { e.stopPropagation(); remove(item.asin); }}
                          style={{ background: '#ef444422', border: 'none', color: '#ef4444', borderRadius: 6, padding: '4px 6px', cursor: 'pointer' }}
                          title="Remove"
                        >
                          <Trash2 size={12} />
                        </button>
                      </div>
                    </div>
                    <div style={{ fontSize: 10, color: '#475569', marginTop: 4 }}>
                      <span style={{ width: 6, height: 6, borderRadius: '50%', background: statusColor(item.status), display: 'inline-block', marginRight: 4 }} />
                      {item.status} · {item.scraped_at ? new Date(item.scraped_at).toLocaleTimeString() : ''}
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>

          {/* Detail Panel */}
          {selected && (
            <div style={{ display: 'flex', flexDirection: 'column', gap: 20 }}>

              {/* Product Card */}
              <div style={{ background: '#1e293b', border: '1px solid #334155', borderRadius: 16, overflow: 'hidden' }}>
                <div style={{
                  padding: '16px 24px', borderBottom: '1px solid #334155',
                  background: 'linear-gradient(135deg,#1e3a5f,#1e293b)',
                  display: 'flex', justifyContent: 'space-between', alignItems: 'center'
                }}>
                  <div style={{ fontWeight: 700, fontSize: 16 }}>📦 Product Detail</div>
                  <a
                    href={selected.url} target="_blank" rel="noreferrer"
                    style={{ color: '#f59e0b', fontSize: 13, display: 'flex', alignItems: 'center', gap: 4, textDecoration: 'none' }}
                  >
                    View on Amazon <ExternalLink size={12} />
                  </a>
                </div>
                <div style={{ padding: 24, display: 'flex', gap: 24 }}>
                  {selected.image_url && (
                    <img
                      src={selected.image_url} alt={selected.title}
                      style={{ width: 120, height: 120, objectFit: 'contain', borderRadius: 10, background: '#fff', padding: 8 }}
                    />
                  )}
                  <div style={{ flex: 1 }}>
                    <div style={{ fontWeight: 700, fontSize: 16, lineHeight: 1.4, marginBottom: 12, color: '#f1f5f9' }}>
                      {selected.title}
                    </div>
                    <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3,1fr)', gap: 16 }}>
                      <div style={{ background: '#0f172a', borderRadius: 12, padding: '14px 18px' }}>
                        <div style={{ fontSize: 11, color: '#64748b', fontWeight: 600, marginBottom: 4 }}>BUYBOX PRICE</div>
                        <div style={{ fontSize: 26, fontWeight: 800, color: '#10b981' }}>
                          {fmt(selected.buybox_price, selected.currency === 'USD' ? '$' : '£')}
                        </div>
                      </div>
                      <div style={{ background: '#0f172a', borderRadius: 12, padding: '14px 18px' }}>
                        <div style={{ fontSize: 11, color: '#64748b', fontWeight: 600, marginBottom: 4 }}>BUYBOX SELLER</div>
                        <div style={{ fontSize: 16, fontWeight: 700, color: selected.is_amazon_seller ? '#f59e0b' : '#6366f1' }}>
                          {selected.buybox_seller}
                        </div>
                        <div style={{ fontSize: 11, color: '#64748b', marginTop: 2 }}>
                          {selected.is_amazon_seller ? '⚡ Amazon Direct' : '🛒 Third Party'}
                        </div>
                      </div>
                      <div style={{ background: '#0f172a', borderRadius: 12, padding: '14px 18px' }}>
                        <div style={{ fontSize: 11, color: '#64748b', fontWeight: 600, marginBottom: 4 }}>RATING</div>
                        <div style={{ fontSize: 18, fontWeight: 700, color: '#f59e0b', display: 'flex', alignItems: 'center', gap: 4 }}>
                          <Star size={16} fill="#f59e0b" /> {selected.rating || 'N/A'}
                        </div>
                        <div style={{ fontSize: 11, color: '#64748b', marginTop: 2 }}>
                          {selected.review_count ? `${selected.review_count} reviews` : ''}
                        </div>
                      </div>
                    </div>
                    <div style={{ display: 'flex', gap: 10, marginTop: 14, flexWrap: 'wrap' }}>
                      <Badge color="#6366f1">ASIN: {selected.asin}</Badge>
                      <Badge color={statusColor(selected.status)}>{selected.status}</Badge>
                      {selected.availability && <Badge color="#10b981">{selected.availability.substring(0, 30)}</Badge>}
                      <Badge color="#64748b">{selected.marketplace}</Badge>
                    </div>
                  </div>
                </div>
              </div>

              {/* Price History Chart */}
              <div style={{ background: '#1e293b', border: '1px solid #334155', borderRadius: 16, padding: 24 }}>
                <div style={{ fontWeight: 700, fontSize: 15, marginBottom: 16, display: 'flex', alignItems: 'center', gap: 8 }}>
                  <Activity size={18} color="#6366f1" /> Price History
                  <span style={{ fontSize: 12, color: '#64748b', fontWeight: 400 }}>({chartData.length} data points)</span>
                </div>
                {chartData.length > 1 ? (
                  <ResponsiveContainer width="100%" height={220}>
                    <LineChart data={chartData}>
                      <CartesianGrid strokeDasharray="3 3" stroke="#334155" />
                      <XAxis dataKey="time" stroke="#475569" tick={{ fontSize: 11 }} />
                      <YAxis stroke="#475569" tick={{ fontSize: 11 }} tickFormatter={v => `£${v}`} />
                      <Tooltip
                        contentStyle={{ background: '#1e293b', border: '1px solid #334155', borderRadius: 8 }}
                        labelStyle={{ color: '#94a3b8' }}
                        formatter={(v) => [`£${parseFloat(v).toFixed(2)}`, 'Price']}
                      />
                      <Line type="monotone" dataKey="price" stroke="#f59e0b" strokeWidth={2} dot={{ fill: '#f59e0b', r: 4 }} />
                    </LineChart>
                  </ResponsiveContainer>
                ) : (
                  <div style={{
                    height: 120, display: 'flex', alignItems: 'center', justifyContent: 'center',
                    color: '#475569', flexDirection: 'column', gap: 8
                  }}>
                    <BarChart2 size={32} style={{ opacity: 0.3 }} />
                    <div style={{ fontSize: 13 }}>Refresh a few times to build price history</div>
                  </div>
                )}
              </div>

              {/* History Table */}
              {history.length > 0 && (
                <div style={{ background: '#1e293b', border: '1px solid #334155', borderRadius: 16, overflow: 'hidden' }}>
                  <div style={{ padding: '14px 20px', borderBottom: '1px solid #334155', fontWeight: 700, fontSize: 14 }}>
                    🕐 Snapshot History
                  </div>
                  <div style={{ maxHeight: 240, overflowY: 'auto' }}>
                    <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 13 }}>
                      <thead>
                        <tr style={{ background: '#0f172a' }}>
                          <th style={{ padding: '10px 20px', textAlign: 'left', color: '#64748b', fontWeight: 600 }}>Time</th>
                          <th style={{ padding: '10px 20px', textAlign: 'left', color: '#64748b', fontWeight: 600 }}>Price</th>
                          <th style={{ padding: '10px 20px', textAlign: 'left', color: '#64748b', fontWeight: 600 }}>Seller</th>
                          <th style={{ padding: '10px 20px', textAlign: 'left', color: '#64748b', fontWeight: 600 }}>Change</th>
                        </tr>
                      </thead>
                      <tbody>
                        {[...history].reverse().map((h, i, arr) => {
                          const prev = arr[i + 1];
                          const change = prev ? h.price - prev.price : null;
                          return (
                            <tr key={i} style={{ borderTop: '1px solid #1e293b' }}>
                              <td style={{ padding: '10px 20px', color: '#64748b' }}>
                                {new Date(h.timestamp).toLocaleString()}
                              </td>
                              <td style={{ padding: '10px 20px', fontWeight: 700, color: '#10b981' }}>
                                £{parseFloat(h.price).toFixed(2)}
                              </td>
                              <td style={{ padding: '10px 20px', color: '#94a3b8' }}>{h.seller}</td>
                              <td style={{ padding: '10px 20px' }}>
                                {change !== null ? (
                                  <span style={{
                                    color: change > 0 ? '#ef4444' : change < 0 ? '#10b981' : '#64748b',
                                    display: 'flex', alignItems: 'center', gap: 4, fontSize: 12
                                  }}>
                                    {change > 0 ? <TrendingUp size={12} /> : change < 0 ? <TrendingDown size={12} /> : null}
                                    {change !== 0 ? `£${Math.abs(change).toFixed(2)}` : 'No change'}
                                  </span>
                                ) : <span style={{ color: '#475569', fontSize: 12 }}>—</span>}
                              </td>
                            </tr>
                          );
                        })}
                      </tbody>
                    </table>
                  </div>
                </div>
              )}
            </div>
          )}
        </div>
      </div>

      <style>{`
        @keyframes spin { to { transform: rotate(360deg); } }
        @keyframes pulse { 0%,100%{opacity:1} 50%{opacity:0.4} }
        * { box-sizing: border-box; }
        ::-webkit-scrollbar { width: 6px; }
        ::-webkit-scrollbar-track { background: #1e293b; }
        ::-webkit-scrollbar-thumb { background: #334155; border-radius: 3px; }
        input:focus { border-color: #f59e0b !important; box-shadow: 0 0 0 2px #f59e0b22; }
      `}</style>
    </div>
  );
}
