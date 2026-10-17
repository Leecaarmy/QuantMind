import React from 'react';
import dayjs from 'dayjs';
import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, afterEach, describe, expect, it, vi } from 'vitest';
import { MarketAnalysisPage } from '../MarketAnalysisPage';

const chart = vi.hoisted(() => ({
  setOption: vi.fn(), resize: vi.fn(), clear: vi.fn(),
  on: vi.fn(), off: vi.fn(), dispose: vi.fn(),
}));
vi.mock('echarts', () => ({
  init: vi.fn(() => chart),
  graphic: { LinearGradient: class {} },
}));
vi.mock('../../../../config/services', () => ({ SERVICE_ENDPOINTS: { USER_SERVICE: '/api/v1' } }));
vi.mock('antd', () => ({
  Input: ({ prefix, ...props }: any) => <input {...props} />,
  DatePicker: ({ value, onChange, disabled }: any) => (
    <input aria-label="快照日期" value={value?.format('YYYY-MM-DD') || ''} disabled={disabled}
      onChange={(event) => onChange(event.target.value ? dayjs(event.target.value) : null)} />
  ),
  Spin: () => null,
  message: { info: vi.fn(), success: vi.fn(), error: vi.fn() },
}));
vi.mock('../../components/BroadMarketHeader', () => ({
  BroadMarketHeader: ({ indices }: any) => <div data-testid="indices">{indices.map((item: any) => item.name).join(',')}</div>,
}));
vi.mock('../../components/ShenwanHeatmapChart', () => ({
  ShenwanHeatmapChart: ({ data }: any) => <div data-testid="heatmap">{data.map((item: any) => item.name).join(',')}</div>,
}));
vi.mock('../../components/CapitalFlowSankeyChart', () => ({ CapitalFlowSankeyChart: () => null }));
vi.mock('../../components/MarketBreadthCard', () => ({ MarketBreadthCard: () => null }));
vi.mock('../../components/StockMoneyFlowTable', () => ({ StockMoneyFlowTable: () => null }));
vi.mock('../../components/TagLookupPanel', () => ({ TagLookupPanel: () => null }));

const response = (data: unknown) => ({ ok: true, json: async () => data }) as Response;
const fetchMock = vi.fn();
const urlOf = (input: unknown) => new URL(String(input), 'http://localhost');
const callsFor = (path: string) => fetchMock.mock.calls.filter(([input]) => urlOf(input).pathname.endsWith(path));

function reply(input: unknown) {
  const url = urlOf(input);
  const date = url.searchParams.get('date') || '2026-10-15';
  const empty = date === '2026-10-12';
  if (url.pathname.endsWith('/snapshot/dates')) return response({ dates: ['2026-10-15', '2026-10-14', '2026-10-13', '2026-10-12'] });
  // 走手动分析后的 GET 刷新分支，无需模拟分析计算。
  if (url.pathname.endsWith('/analyze/stream')) return response(null);
  if (url.pathname.endsWith('/indices/overview')) return response(empty ? [] : [{ name: `index-${date}` }]);
  if (url.pathname.endsWith('/breadth')) return response({ trade_date: date, total_turnover_yi: empty ? 0 : 100 });
  if (url.pathname.endsWith('/heatmap')) return response({ items: empty ? [] : [{ name: `sector-${date}` }] });
  if (url.pathname.endsWith('/money-flow/period')) return response({ items: empty ? [] : [{
    id: date, name: `flow-${date}`, pct_change: 1, net_inflow: 1e8,
    main_ratio: 1, super_large: 1e8, large: 0, medium: 0, small: 0,
  }] });
  if (url.pathname.endsWith('/money-flow/stocks/full')) return response(empty ? [] : [{ name: `stock-${date}`, symbol: '600000.SH' }]);
  if (url.pathname.endsWith('/money-flow/sankey')) return response({ nodes: [], links: [] });
  return response([]);
}

function selectDate(date: string) {
  fireEvent.change(screen.getByLabelText('快照日期'), { target: { value: date } });
}

async function expectFlow(date: string) {
  await waitFor(() => expect(chart.setOption).toHaveBeenLastCalledWith(
    expect.objectContaining({ yAxis: expect.objectContaining({ data: [`flow-${date}`] }) }), true,
  ));
}

beforeEach(() => {
  vi.clearAllMocks();
  fetchMock.mockReset().mockImplementation(async (input) => reply(input));
  vi.stubGlobal('fetch', fetchMock);
});
afterEach(() => vi.unstubAllGlobals());

describe('市场分析历史日期', () => {
  it('手动分析后切历史日期，所有行情请求退出实时模式并传入日期', async () => {
    render(<MarketAnalysisPage />);
    await screen.findByText('index-2026-10-15');
    fireEvent.click(screen.getByRole('button', { name: '多周期资金流向' }));
    await expectFlow('2026-10-15');
    fireEvent.click(screen.getByTitle('从本地 QuantDB 读取最新数据并重新执行全市场多维分析'));
    await waitFor(() => expect(urlOf(callsFor('/money-flow/period').at(-1)![0]).searchParams.get('realtime')).toBe('1'));
    await waitFor(() => expect(screen.getByLabelText('快照日期')).not.toBeDisabled());
    selectDate('2026-10-14');
    await expectFlow('2026-10-14');
    await screen.findByText('index-2026-10-14');
    for (const path of ['/indices/overview', '/breadth', '/heatmap', '/money-flow/stocks', '/money-flow/stocks/full', '/money-flow/sankey', '/money-flow/period']) {
      const url = urlOf(callsFor(path).at(-1)![0]);
      expect(url.searchParams.get('date'), path).toBe('2026-10-14');
      expect(url.searchParams.has('realtime'), path).toBe(false);
    }
    fireEvent.click(screen.getByRole('button', { name: '1日' }));
    await waitFor(() => expect(urlOf(callsFor('/money-flow/period').at(-1)![0]).searchParams.get('period')).toBe('1d'));
    expect(urlOf(callsFor('/money-flow/period').at(-1)![0]).searchParams.get('date')).toBe('2026-10-14');
    fireEvent.change(screen.getByPlaceholderText('全局搜索行业或股票...'), { target: { value: 'stock-' } });
    expect(await screen.findByText('stock-2026-10-14')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: '矩形树图' }));
    expect(await screen.findByTestId('heatmap')).toHaveTextContent('sector-2026-10-14');
    fireEvent.click(screen.getByText('最新', { exact: true }));
    await screen.findByText('index-2026-10-15');
    expect(urlOf(callsFor('/indices/overview').at(-1)![0]).search).toBe('');
  });

  it('历史结果为空时清除旧数据，重新选有效日期后恢复绘图', async () => {
    render(<MarketAnalysisPage />);
    await screen.findByText('index-2026-10-15');
    fireEvent.click(screen.getByRole('button', { name: '多周期资金流向' }));
    await expectFlow('2026-10-15');
    selectDate('2026-10-12');
    await screen.findByText('暂无资金流向数据');
    expect(screen.getByTestId('indices')).toBeEmptyDOMElement();
    expect(chart.clear).toHaveBeenCalled();
    selectDate('2026-10-13');
    await expectFlow('2026-10-13');
    await screen.findByText('index-2026-10-13');
  });

  it('快速切日期时取消旧请求，即使旧响应晚到也不覆盖新数据', async () => {
    const pending: Array<() => void> = [];
    fetchMock.mockImplementation((input) => {
      if (urlOf(input).searchParams.get('date') === '2026-10-14') {
        return new Promise<Response>((resolve) => pending.push(() => resolve(reply(input))));
      }
      return Promise.resolve(reply(input));
    });
    render(<MarketAnalysisPage />);
    await screen.findByText('index-2026-10-15');
    fireEvent.click(screen.getByRole('button', { name: '多周期资金流向' }));
    await expectFlow('2026-10-15');
    selectDate('2026-10-14');
    selectDate('2026-10-13');
    await expectFlow('2026-10-13');
    await screen.findByText('index-2026-10-13');
    for (const [, options] of fetchMock.mock.calls.filter(([input]) => urlOf(input).searchParams.get('date') === '2026-10-14')) {
      expect(options.signal.aborted).toBe(true);
    }
    await act(async () => { pending.forEach((resolve) => resolve()); });
    expect(screen.getByTestId('indices')).toHaveTextContent('index-2026-10-13');
    await expectFlow('2026-10-13');
  });
});
