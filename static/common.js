// 通用JavaScript函数 - Curling Masters

// 分页导航功能
function showPage(pageId) {
  // 隐藏所有页面
  const pages = document.querySelectorAll('.page-content');
  pages.forEach(page => {
    page.style.display = 'none';
  });
  
  // 移除所有按钮的active类
  const buttons = document.querySelectorAll('.page-btn');
  buttons.forEach(btn => {
    btn.classList.remove('active');
  });
  
  // 显示选中的页面
  document.getElementById('page-' + pageId).style.display = 'block';
  
  // 激活选中的按钮
  document.getElementById('btn-' + pageId).classList.add('active');
}

// 比分着色功能
function parseScore(text) {
  if (text === null || text === undefined) return null;
  text = String(text).trim();
  if (text === '') return null;
  var n = parseInt(text, 10);
  return isNaN(n) ? null : n;
}

function applyScoreStyles() {
  // 仅选择比赛表格的行
  var rows = document.querySelectorAll('.cm-matches-table tbody tr');
  rows.forEach(function(row) {
    var cells = row.querySelectorAll('td');
    if (cells.length < 4) return;
    var leftCell = cells[1];
    var rightCell = cells[2];
    var leftScore = parseScore(leftCell.textContent);
    var rightScore = parseScore(rightCell.textContent);

    leftCell.classList.remove('left-win','right-win','draw-left','draw-right');
    rightCell.classList.remove('left-win','right-win','draw-left','draw-right');

    if (leftScore === null || rightScore === null) return;

    if (leftScore > rightScore) {
      leftCell.classList.add('left-win');
    } else if (rightScore > leftScore) {
      rightCell.classList.add('right-win');
    } else {
      leftCell.classList.add('draw-left');
      rightCell.classList.add('draw-right');
    }
  });
}

// 初始化比分着色
if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', applyScoreStyles);
} else {
  applyScoreStyles();
}
