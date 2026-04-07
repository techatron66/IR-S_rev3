(function () {
  const sidebar = document.querySelector('.sidebar');
  const toggle  = document.querySelector('.sidebar-toggle');
  if (!sidebar || !toggle) return;

  const ICONS = {
    collapse: `<svg width="14" height="14" viewBox="0 0 14 14" fill="none">
      <path d="M9 2L4 7l5 5" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"/>
    </svg>`,
    expand: `<svg width="14" height="14" viewBox="0 0 14 14" fill="none">
      <path d="M5 2l5 5-5 5" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"/>
    </svg>`
  };

  let collapsed = localStorage.getItem('iris_sb') === '1';
  apply(collapsed, false);

  toggle.addEventListener('click', () => { 
    collapsed = !collapsed; 
    localStorage.setItem('iris_sb', collapsed ? '1' : '0'); 
    apply(collapsed, true); 
  });

  function apply(state, animate) {
    if (!animate) { 
      sidebar.style.transition = 'none'; 
      requestAnimationFrame(() => requestAnimationFrame(() => sidebar.style.transition = '')); 
    }
    sidebar.classList.toggle('collapsed', state);
    toggle.innerHTML = state ? ICONS.expand : ICONS.collapse;
    toggle.title = state ? 'Expand sidebar' : 'Collapse sidebar';
  }
})();

function openModal(id) {
  const el = document.getElementById(id);
  if (!el) return;
  el.classList.remove('closing');
  el.style.display = 'flex';
  document.body.style.overflow = 'hidden';
}

function closeModal(id) {
  const el = document.getElementById(id);
  if (!el) return;
  el.classList.add('closing');
  el.addEventListener('animationend', () => {
    el.style.display = 'none';
    el.classList.remove('closing');
    document.body.style.overflow = '';
  }, { once: true });
}

document.addEventListener('DOMContentLoaded', () => {
  document.querySelectorAll('.modal-backdrop').forEach(b => {
    b.addEventListener('click', e => { if (e.target === b) closeModal(b.id); });
  });
  document.addEventListener('keydown', e => {
    if (e.key !== 'Escape') return;
    const open = document.querySelector('.modal-backdrop[style*="flex"]:not(.closing)');
    if (open) closeModal(open.id);
  });
  document.querySelectorAll('.dropzone').forEach(dz => {
    dz.addEventListener('dragover', e => { e.preventDefault(); dz.classList.add('over'); });
    dz.addEventListener('dragleave', () => dz.classList.remove('over'));
    dz.addEventListener('drop', e => { e.preventDefault(); dz.classList.remove('over'); });
  });
});

function showToast(message, type, duration) {
  type = type || 'default'; 
  duration = duration || 3200;
  let shelf = document.querySelector('.toast-shelf');
  if (!shelf) { 
    shelf = document.createElement('div'); 
    shelf.className = 'toast-shelf'; 
    document.body.appendChild(shelf); 
  }

  const DOT = { success: '#30D158', error: '#FF453A', warning: '#FFD60A' };
  const dot = DOT[type] ? `<span style="width:7px;height:7px;border-radius:50%;background:${DOT[type]};flex-shrink:0"></span>` : '';

  const t = document.createElement('div');
  t.className = 'toast';
  t.innerHTML = dot + `<span style="flex:1">${message}</span>`;
  shelf.appendChild(t);
  setTimeout(() => {
    t.classList.add('out');
    t.addEventListener('animationend', () => t.remove(), { once: true });
  }, duration);
}
