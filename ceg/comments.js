/* CEG 飲み部図鑑 — コメント欄（各メンバーページ共有）
 * slug は URL から自動判定（/nene/ → "nene"）。
 * 表示は textContent で挿入するため、保存値に何が入っていてもXSSにならない。
 */
(function () {
  "use strict";
  var API = "/api/comments";

  var parts = location.pathname.split("/").filter(Boolean);
  var slug = parts.length ? parts[0] : "";

  var form = document.getElementById("cForm");
  var listEl = document.getElementById("cList");
  if (!slug || !form || !listEl) return;

  var nickEl = document.getElementById("cNick");
  var msgEl = document.getElementById("cMsg");
  var hpEl = document.getElementById("cHp");
  var statusEl = document.getElementById("cStatus");
  var countEl = document.getElementById("cCount");
  var submitEl = form.querySelector(".c-submit");

  function fmt(iso) {
    var d = new Date(iso);
    if (isNaN(d.getTime())) return "";
    var p = function (n) { return ("0" + n).slice(-2); };
    return (
      d.getFullYear() + "/" + p(d.getMonth() + 1) + "/" + p(d.getDate()) +
      " " + p(d.getHours()) + ":" + p(d.getMinutes())
    );
  }

  function setStatus(text, isError) {
    statusEl.className = "c-status" + (isError ? " error" : "");
    statusEl.textContent = text || "";
  }

  function showEmpty(text) {
    listEl.textContent = "";
    var li = document.createElement("li");
    li.className = "c-empty";
    li.textContent = text;
    listEl.appendChild(li);
  }

  function render(items) {
    if (countEl) countEl.textContent = items.length ? "(" + items.length + ")" : "";
    if (!items.length) {
      showEmpty("まだコメントはありません。最初のひとことをどうぞ。");
      return;
    }
    listEl.textContent = "";
    items.forEach(function (c) {
      var li = document.createElement("li");

      var head = document.createElement("div");
      head.className = "c-item-head";
      var nick = document.createElement("span");
      nick.className = "c-item-nick";
      nick.textContent = c.nickname;
      var time = document.createElement("span");
      time.className = "c-item-time";
      time.textContent = fmt(c.created_at);
      head.appendChild(nick);
      head.appendChild(time);

      var msg = document.createElement("div");
      msg.className = "c-item-msg";
      msg.textContent = c.message;

      li.appendChild(head);
      li.appendChild(msg);
      listEl.appendChild(li);
    });
  }

  function load() {
    fetch(API + "?slug=" + encodeURIComponent(slug), {
      headers: { Accept: "application/json" }
    })
      .then(function (r) { return r.ok ? r.json() : Promise.reject(r); })
      .then(function (data) { render((data && data.comments) || []); })
      .catch(function () { showEmpty("コメントを読み込めませんでした。"); });
  }

  form.addEventListener("submit", function (e) {
    e.preventDefault();
    setStatus("");

    var nickname = (nickEl.value || "").trim();
    var message = (msgEl.value || "").trim();
    if (!nickname || !message) {
      setStatus("ニックネームとメッセージを入力してください。", true);
      return;
    }
    // ハニーポットが埋まっていたら（=bot）送信せず成功風に終える
    if (hpEl && hpEl.value) {
      msgEl.value = "";
      setStatus("送信しました。");
      return;
    }

    submitEl.disabled = true;
    setStatus("送信中…");

    fetch(API, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        slug: slug,
        nickname: nickname,
        message: message,
        website: hpEl ? hpEl.value : ""
      })
    })
      .then(function (r) {
        if (r.status === 429) return Promise.reject("rate");
        return r.ok ? r.json() : Promise.reject("err");
      })
      .then(function () {
        msgEl.value = "";
        setStatus("送信しました！");
        load();
      })
      .catch(function (kind) {
        setStatus(
          kind === "rate"
            ? "投稿が早すぎます。少し待ってからどうぞ。"
            : "送信に失敗しました。",
          true
        );
      })
      .finally(function () { submitEl.disabled = false; });
  });

  load();
})();
