library(jsonlite)
cfg <- fromJSON('out/reference_config.json', simplifyVector=FALSE)
plans <- cfg$plans
frame <- read.csv(plans[[1]]$file, check.names=FALSE, na.strings=c('', ' '))
id <- plans[[1]]$id_column
frame$.subject <- as.character(frame[[id]])
frame <- frame[order(frame$.subject, method='radix'),]
indexes <- list()
for (n in c(nrow(frame),nrow(frame)-1)) indexes[[as.character(n)]] <- as.matrix(read.csv(paste0('out/bootstrap_indices_',n,'.csv'),header=FALSE))+1L
results <- list()
for (base in cfg$bases) {
  sample <- if (is.null(base$omitted)) frame else frame[frame$.subject != base$omitted,]
  n <- nrow(sample)
  loc <- function(x) mean(x, trim=if(base$estimator=='trim20') .2 else 0)
  vals <- lapply(seq_along(plans), function(j) {
    plan <- plans[[j]]
    d <- sample[[plan$x]] - sample[[plan$y]]
    if (j==1 && base$scale=='log_ratio') d <- log(sample[[plan$x]] / sample[[plan$y]])
    theta <- loc(d)
    if (base$procedure=='paired_t') {
      test <- t.test(d)
      se <- sd(d)/sqrt(n); p <- test$p.value; ci <- test$conf.int; symmetric <- ci; bca <- NULL
    } else {
      ix <- indexes[[as.character(n)]]
      boot <- apply(ix,1,function(k) loc(d[k]))
      p <- (1+sum(abs(boot-theta)>=abs(theta)))/(length(boot)+1)
      se <- sd(boot); ci <- quantile(boot,c(.025,.975),type=7,names=FALSE)
      width <- quantile(abs(boot-theta),.95,type=7,names=FALSE); symmetric <- theta+c(-width,width)
      bca <- NULL
      if(is.null(base$omitted)) {
        ties <- abs(boot-theta) <= 1e-12 + 1e-12*abs(theta)
        rank <- (sum(boot<theta & !ties)+.5*sum(ties))/length(boot)
        z0 <- qnorm(max(.5/length(boot),min(1-.5/length(boot),rank)))
        jack <- vapply(seq_along(d),function(i) loc(d[-i]),0.)
        influence <- mean(jack)-jack
        denom <- 6*sum(influence^2)^1.5
        if(!is.finite(denom) || denom==0 || diff(range(boot))==0) stop('Undefined BCa interval')
        acceleration <- sum(influence^3)/denom
        z <- qnorm(c(.025,.975))
        probs <- pnorm(z0+(z0+z)/(1-acceleration*(z0+z)))
        bca <- quantile(boot,probs,type=7,names=FALSE)
      }
    }
    list(estimate=theta,se=se,p_raw=p,ci_lower=ci[1],ci_upper=ci[2],ci_symmetric_lower=symmetric[1],ci_symmetric_upper=symmetric[2],n=n,bca=bca)
  })
  for (row in cfg$rows) if(row$base_id==base$base_id) {
    value <- vals[[1]]
    if(row$interval=='bca') {value$ci_lower <- value$bca[1];value$ci_upper <- value$bca[2]}
    value$p <- p.adjust(vapply(vals,function(v) v$p_raw,0.),method=row$multiplicity)[1]
    value$spec_id <- row$spec_id
    results[[length(results)+1]] <- value
  }
}
write_json(results,'out/reference_results.json',auto_unbox=TRUE,digits=17,null='null')
