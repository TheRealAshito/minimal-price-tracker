/**
 * Chart utilities for Minimal Price Tracker
 */

const COLORS = {
    kabum: { bg: 'rgba(234, 179, 8, 0.2)', border: 'rgb(234, 179, 8)' },
    shopee: { bg: 'rgba(249, 115, 22, 0.2)', border: 'rgb(249, 115, 22)' },
    amazon: { bg: 'rgba(59, 130, 246, 0.2)', border: 'rgb(59, 130, 246)' },
};

function createStoreColor(store) {
    return COLORS[store] || { bg: 'rgba(148, 163, 184, 0.2)', border: 'rgb(148, 163, 184)' };
}

function formatBRL(value) {
    return new Intl.NumberFormat('pt-BR', {
        style: 'currency',
        currency: 'BRL'
    }).format(value);
}

function formatDate(dateStr) {
    return new Date(dateStr).toLocaleDateString('pt-BR', {
        day: '2-digit',
        month: '2-digit',
        year: 'numeric',
        hour: '2-digit',
        minute: '2-digit'
    });
}

/**
 * Create a price history line chart
 */
function createPriceChart(canvasId, historyData, productName) {
    const ctx = document.getElementById(canvasId);
    if (!ctx) return null;

    const successData = historyData
        .filter(h => h.status === 'success' && h.price)
        .reverse();

    const labels = successData.map(h => formatDate(h.scraped_at));
    const prices = successData.map(h => h.price);

    return new Chart(ctx, {
        type: 'line',
        data: {
            labels: labels,
            datasets: [{
                label: productName || 'Price',
                data: prices,
                borderColor: 'rgb(99, 102, 241)',
                backgroundColor: 'rgba(99, 102, 241, 0.1)',
                fill: true,
                tension: 0.3,
                pointRadius: 3,
                pointHoverRadius: 6,
            }]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            plugins: {
                legend: { display: false },
                tooltip: {
                    callbacks: {
                        label: (ctx) => formatBRL(ctx.parsed.y)
                    }
                }
            },
            scales: {
                x: {
                    ticks: { color: '#94a3b8', maxTicksLimit: 10 },
                    grid: { color: 'rgba(148, 163, 184, 0.1)' }
                },
                y: {
                    ticks: {
                        color: '#94a3b8',
                        callback: (v) => 'R$ ' + v.toLocaleString('pt-BR')
                    },
                    grid: { color: 'rgba(148, 163, 184, 0.1)' }
                }
            }
        }
    });
}

/**
 * Create a comparison bar chart
 */
function createComparisonChart(canvasId, comparisonData) {
    const ctx = document.getElementById(canvasId);
    if (!ctx) return null;

    const labels = comparisonData.map(p => p.name.substring(0, 20));
    const currentPrices = comparisonData.map(p => p.current_price || 0);
    const meanPrices = comparisonData.map(p => p.mean_price || 0);
    const bgColors = comparisonData.map(p => createStoreColor(p.store).bg);
    const borderColors = comparisonData.map(p => createStoreColor(p.store).border);

    return new Chart(ctx, {
        type: 'bar',
        data: {
            labels: labels,
            datasets: [
                {
                    label: 'Preço Atual',
                    data: currentPrices,
                    backgroundColor: bgColors,
                    borderColor: borderColors,
                    borderWidth: 2,
                },
                {
                    label: 'Preço Médio',
                    data: meanPrices,
                    backgroundColor: 'rgba(148, 163, 184, 0.2)',
                    borderColor: 'rgb(148, 163, 184)',
                    borderWidth: 2,
                }
            ]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            plugins: {
                tooltip: {
                    callbacks: {
                        label: (ctx) => ctx.dataset.label + ': ' + formatBRL(ctx.parsed.y)
                    }
                }
            },
            scales: {
                x: {
                    ticks: { color: '#94a3b8' },
                    grid: { color: 'rgba(148, 163, 184, 0.1)' }
                },
                y: {
                    ticks: {
                        color: '#94a3b8',
                        callback: (v) => 'R$ ' + v.toLocaleString('pt-BR')
                    },
                    grid: { color: 'rgba(148, 163, 184, 0.1)' }
                }
            }
        }
    });
}
