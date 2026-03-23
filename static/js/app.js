// フラッシュメッセージを3秒後に自動で消す
document.addEventListener('DOMContentLoaded', function() {
  setTimeout(function() {
    document.querySelectorAll('.flash-messages .alert').forEach(function(el) {
      el.style.transition = 'opacity .4s';
      el.style.opacity = '0';
      setTimeout(function() { el.remove(); }, 400);
    });
  }, 3000);
});
