// Reads the authorizations one at a time (D93). Each request makes at most one PayPal read, so no
// request can outlive the web worker. The button in the form does the same thing without this script.
(function () {
  var form = document.getElementById("preflight-form");
  var progress = document.getElementById("preflight-progress");
  if (!form || !progress || !window.fetch) {
    return;
  }

  // Ask the server to check the next authorization, then update the "Checked N of M" line.
  function checkNext() {
    fetch(form.action, {
      method: "POST",
      credentials: "same-origin",
      headers: { "Content-Type": "application/x-www-form-urlencoded" },
      body: new URLSearchParams(new FormData(form))
    })
      .then(function (response) {
        if (!response.ok) {
          throw new Error("refused");
        }
        return response.json();
      })
      .then(function (answer) {
        progress.textContent = "Checked " + answer.checked + " of " + answer.total + " authorizations.";
        if (answer.error) {
          progress.textContent += " One authorization could not be read. Use the button to try again.";
          return;
        }
        if (answer.done) {
          window.location.reload();
          return;
        }
        checkNext();
      })
      .catch(function () {
        progress.textContent += " The check stopped. Use the button to try again.";
      });
  }

  form.addEventListener("submit", function (event) {
    event.preventDefault();
    checkNext();
  });
  checkNext();
})();
