/* Which API the pages talk to. On a local machine (http://localhost or 127.0.0.1)
   the pages use a local API on port 8000; everywhere else the Render API. */
window.IMX_API = /^(localhost|127\.0\.0\.1)$/.test(location.hostname)
  ? location.protocol + "//" + location.hostname + ":8000"
  : "https://immxrsive-api.onrender.com";
