(function() {
  function fillInteropTable(result) {
    var t = document.getElementById("interop");
    var row = t.insertRow(0);
    row.insertCell(0);
    for(var i = 0; i < result.servers.length; i++) {
      row.insertCell(i+1).innerHTML = result.servers[i];
    }
    var index = 0;
    for(var i = 0; i < result.clients.length; i++) {
      var row = t.insertRow(i+1);
      row.insertCell(0).innerHTML = result.clients[i];
      for(var j = 0; j < result.servers.length; j++) {
        var cell = row.insertCell(j+1);
        cell.className = "results";
        var succeeded = document.createElement("div");
        succeeded.className = "text-success";
        succeeded.innerHTML = result.results[index].succeeded;
        cell.appendChild(succeeded);
        var unsupported = document.createElement("div");
        unsupported.className = "text-warning";
        unsupported.innerHTML = result.results[index].unsupported;
        cell.appendChild(unsupported);
        var failed = document.createElement("div");
        failed.className = "text-danger";
        failed.innerHTML = result.results[index].failed;
        cell.appendChild(failed);
        index++;
      }
    }
  }

  function fillMeasurementTable(result) {
    var t = document.getElementById("measurements");
    var row = t.insertRow(0);
    row.insertCell(0);
    for(var i = 0; i < result.servers.length; i++) {
      row.insertCell(i+1).innerHTML = result.servers[i];
    }
    var index = 0;
    for(var i = 0; i < result.clients.length; i++) {
      var row = t.insertRow(i+1);
      row.insertCell(0).innerHTML = result.clients[i];
      for(var j = 0; j < result.servers.length; j++) {
        var res = result.measurements[index];
        var cell = row.insertCell(j+1);
        cell.className = "results";
        for(var k = 0; k < res.length; k++) {
          var measurement = res[k];
          var el = document.createElement("div");
          switch(measurement.result) {
            case "succeeded":
              el.className = "text-success";
              el.innerHTML = measurement.name + ": " + measurement.details;
              break;
            case "unsupported":
              el.className = "text-warning";
              el.innerHTML = measurement.name;
              break;
            case "failed":
              el.className = "text-danger";
              el.innerHTML = measurement.name;
              break;
          }
          cell.appendChild(el);
        }
        index++;
      }
    }
  }

  function process(result) {
    var d = new Date(1000*result.timestamp);
    document.getElementById("lastrun").innerHTML = d.toLocaleDateString("en-US") + " " + d.toLocaleTimeString("en-US");

    fillInteropTable(result)
    fillMeasurementTable(result)
  }

  var xhr = new XMLHttpRequest();
  xhr.responseType = 'json';
  xhr.open('GET', 'result.json');

  xhr.onreadystatechange = function() {
    if(xhr.readyState !== XMLHttpRequest.DONE) {
      return;
    }
    if(xhr.status != 200) {
      console.log("Received status");
      console.log(xhr.status);
      return;
    }
    process(xhr.response);
  };
  xhr.send();
})();
