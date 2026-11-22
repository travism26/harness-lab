package lab.springsandbox.web;

import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.webmvc.test.autoconfigure.WebMvcTest;
import org.springframework.test.web.servlet.MockMvc;

@WebMvcTest(PassRateController.class)
class PassRateControllerTest {

    @Autowired
    private MockMvc mvc;

    @Test
    void returnsThePassRate() throws Exception {
        mvc.perform(get("/pass-rate").param("passed", "3").param("total", "4"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.passed").value(3))
                .andExpect(jsonPath("$.total").value(4))
                .andExpect(jsonPath("$.percent").value(75));
    }

    @Test
    void rejectsAnInvalidPair() throws Exception {
        mvc.perform(get("/pass-rate").param("passed", "5").param("total", "4"))
                .andExpect(status().isBadRequest());
        mvc.perform(get("/pass-rate").param("passed", "0").param("total", "0"))
                .andExpect(status().isBadRequest());
    }
}
