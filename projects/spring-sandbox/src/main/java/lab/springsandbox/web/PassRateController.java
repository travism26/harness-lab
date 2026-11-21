package lab.springsandbox.web;

import lab.springsandbox.domain.PassRate;
import org.springframework.http.HttpStatus;
import org.springframework.web.bind.annotation.ExceptionHandler;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.ResponseStatus;
import org.springframework.web.bind.annotation.RestController;

/** Serves the pass-rate endpoint. */
@RestController
public class PassRateController {

    /** The JSON body of a pass rate. */
    record Body(int passed, int total, int percent) {
    }

    /** Returns the pass rate for the given counts. */
    @GetMapping("/pass-rate")
    Body passRate(@RequestParam int passed, @RequestParam int total) {
        PassRate rate = new PassRate(passed, total);
        return new Body(rate.passed(), rate.total(), rate.percent());
    }

    @ExceptionHandler(IllegalArgumentException.class)
    @ResponseStatus(HttpStatus.BAD_REQUEST)
    void invalid() {
    }
}
